from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.app.features.legacy_import.inspect import LegacyInspectionReport, inspect_source
from backend.app.features.legacy_import.service import ImportedBatch, LegacyImportService


class LegacyImportConfirmationError(ValueError):
    """Raised when an import confirmation is absent, stale, or already consumed."""


@dataclass(frozen=True)
class LegacyImportSource:
    source_id: str
    label: str


@dataclass(frozen=True)
class LegacyImportPreview:
    source_id: str
    portfolio_id: str
    effective_at: datetime
    current_position_count: int
    historical_position_count: int
    source_file_count: int
    quality_tags: tuple[str, ...]
    confirmation_token: str


@dataclass(frozen=True)
class LegacyImportResult:
    batch_id: str
    manifest_sha256: str
    raw_file_count: int
    opening_position_count: int
    historical_snapshot_count: int
    idempotent: bool


@dataclass(frozen=True)
class _Confirmation:
    source_id: str
    portfolio_id: str
    effective_at: datetime
    fingerprint: str


class LegacyImportWebService:
    """Expose a narrow, browser-safe facade over the explicit legacy importer."""

    def __init__(
        self,
        *,
        imports_root: Path,
        source_roots: tuple[Path, ...],
        import_source: Callable[[Path, str, datetime], ImportedBatch] | None = None,
        result_reader: Callable[[str], LegacyImportResult | None] | None = None,
        repository_factory: Callable[[], object] | None = None,
    ) -> None:
        self._imports_root = imports_root
        self._source_roots = tuple(root.resolve() for root in source_roots)
        self._confirmations: dict[str, _Confirmation] = {}
        self._result_reader = result_reader
        if import_source is not None:
            self._import_source = import_source
        elif repository_factory is not None:
            repository = repository_factory()
            importer = LegacyImportService(imports_root, repository)  # type: ignore[arg-type]
            self._import_source = lambda source, portfolio, effective: importer.import_source(
                source_root=source,
                portfolio_id=portfolio,
                effective_at=effective,
            )
            self._result_reader = getattr(repository, "get_summary", None)
        else:
            raise ValueError("legacy import web service requires an importer")

    def sources(self) -> tuple[LegacyImportSource, ...]:
        sources: list[LegacyImportSource] = []
        for root in self._source_roots:
            candidates = (root,) if self._is_source(root) else tuple(sorted(root.glob("*")))
            for candidate in candidates:
                if self._is_source_under(root, candidate):
                    sources.append(LegacyImportSource(candidate.name, candidate.name))
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("configured legacy import source labels must be unique")
        return tuple(sorted(sources, key=lambda source: source.source_id))

    def resolve_source(self, source_id: str) -> Path:
        for source in self.sources():
            if secrets.compare_digest(source.source_id, source_id):
                for root in self._source_roots:
                    candidate = (root / source_id).resolve()
                    if candidate.name == source_id and self._is_source_under(root, candidate):
                        return candidate
                    if root.name == source_id and self._is_source_under(root, root):
                        return root
        raise KeyError(source_id)

    def preview(
        self,
        source_id: str,
        portfolio_id: str,
        effective_at: datetime,
    ) -> LegacyImportPreview:
        self._require_aware(effective_at)
        source = self.resolve_source(source_id)
        report = inspect_source(source)
        current = report.source_root / "data" / "holdings" / "持仓.csv"
        current_count = len(LegacyImportService._parse_opening(current, effective_at))
        historical_count = sum(
            len(LegacyImportService._parse_history(item.path, item.snapshot_at, item.sha256))
            for item in report.files
            if item.snapshot_at is not None
        )
        token = secrets.token_urlsafe(32)
        self._confirmations[token] = _Confirmation(
            source_id,
            portfolio_id,
            effective_at,
            self._fingerprint(report),
        )
        return LegacyImportPreview(
            source_id,
            portfolio_id,
            effective_at,
            current_count,
            historical_count,
            len(report.files),
            tuple(tag.value for tag in report.tags),
            token,
        )

    def confirm(
        self,
        confirmation_token: str,
        source_id: str,
        portfolio_id: str,
        effective_at: datetime,
    ) -> LegacyImportResult:
        confirmation = self._confirmations.pop(confirmation_token, None)
        if confirmation is None or confirmation != _Confirmation(
            source_id,
            portfolio_id,
            effective_at,
            self._fingerprint(inspect_source(self.resolve_source(source_id))),
        ):
            raise LegacyImportConfirmationError("manual confirmation is required")
        batch = self._import_source(self.resolve_source(source_id), portfolio_id, effective_at)
        stored = self.result(batch.batch_id)
        return LegacyImportResult(
            batch_id=stored.batch_id,
            manifest_sha256=stored.manifest_sha256,
            raw_file_count=stored.raw_file_count,
            opening_position_count=stored.opening_position_count,
            historical_snapshot_count=stored.historical_snapshot_count,
            idempotent=batch.idempotent,
        )

    def result(self, batch_id: str) -> LegacyImportResult:
        if self._result_reader is None:
            raise KeyError(batch_id)
        result = self._result_reader(batch_id)
        if isinstance(result, LegacyImportResult):
            return result
        if isinstance(result, dict):
            return LegacyImportResult(**result)
        raise KeyError(batch_id)

    @staticmethod
    def _is_source(path: Path) -> bool:
        return path.is_dir() and (path / "data" / "holdings" / "持仓.csv").is_file()

    @classmethod
    def _is_source_under(cls, root: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return False
        return cls._is_source(path)

    @staticmethod
    def _fingerprint(report: LegacyInspectionReport) -> str:
        files = report.files
        value = [
            {
                "path": str(item.path),
                "sha256": item.sha256,
                "tags": [tag.value for tag in item.tags],
            }
            for item in files
        ]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
