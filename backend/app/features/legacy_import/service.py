from __future__ import annotations
import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from backend.app.core.portfolio.models import OpeningPosition
from .inspect import inspect_source


@dataclass(frozen=True)
class ImportedBatch:
    batch_id: str
    source_root: str
    source_git_state: str
    imported_at: datetime
    effective_at: datetime
    portfolio_id: str
    manifest_sha256: str
    quality_report_json: str
    idempotent: bool = False


@dataclass(frozen=True)
class ImportedHistoricalPosition:
    snapshot_at: datetime
    security_id: str
    quantity: int
    inherited_unit_cost: Decimal
    imported_buy_date: str | None
    source_file_sha256: str
    raw_row_json: str


@dataclass(frozen=True)
class ImportedRawFile:
    relative_path: str
    sha256: str
    quality_tags_json: str


class LegacyRepository(Protocol):
    def save(
        self,
        batch: ImportedBatch,
        raw_files: tuple[ImportedRawFile, ...],
        positions: tuple[OpeningPosition, ...],
        historical_snapshots: tuple[ImportedHistoricalPosition, ...],
    ) -> bool: ...


def _git_state(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "not-a-git-worktree"


class LegacyImportService:
    def __init__(self, imports_root: Path, repository: LegacyRepository) -> None:
        self._imports_root = imports_root.resolve()
        self._repository = repository

    def import_source(
        self, *, source_root: Path, portfolio_id: str, effective_at: datetime
    ) -> ImportedBatch:
        if effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        report = inspect_source(source_root)
        files = tuple(x for x in report.files if x.path.is_file())
        manifest = {
            "portfolio_id": portfolio_id,
            "effective_at": effective_at.isoformat(),
            "files": [
                {"path": str(x.path.relative_to(report.source_root)), "sha256": x.sha256}
                for x in files
            ],
        }
        digest = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        batch_id = digest[:24]
        raw_root = self._imports_root / batch_id / "raw"
        raw = []
        for item in files:
            rel = item.path.relative_to(report.source_root / "data" / "holdings")
            dest = raw_root / ("current" if rel.name == "持仓.csv" else "history") / rel.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copyfile(item.path, dest)
            elif hashlib.sha256(dest.read_bytes()).hexdigest() != item.sha256:
                raise RuntimeError("frozen raw file hash conflict")
            raw.append(
                ImportedRawFile(
                    str(dest.relative_to(self._imports_root / batch_id)),
                    item.sha256,
                    json.dumps([t.value for t in item.tags], ensure_ascii=False),
                )
            )
        current = report.source_root / "data" / "holdings" / "持仓.csv"
        positions = self._parse_opening(current, effective_at)
        snapshots = tuple(
            row
            for item in files
            if item.snapshot_at
            for row in self._parse_history(item.path, item.snapshot_at, item.sha256)
        )
        quality = json.dumps(
            {
                "tags": [t.value for t in report.tags],
                "files": [
                    {
                        "source_path": str(x.path),
                        "sha256": x.sha256,
                        "snapshot_at": x.snapshot_at.isoformat() if x.snapshot_at else None,
                        "tags": [t.value for t in x.tags],
                    }
                    for x in files
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        batch = ImportedBatch(
            batch_id,
            str(report.source_root),
            _git_state(report.source_root),
            datetime.now(UTC),
            effective_at,
            portfolio_id,
            digest,
            quality,
        )
        saved = self._repository.save(batch, tuple(raw), positions, snapshots)
        return ImportedBatch(
            batch.batch_id,
            batch.source_root,
            batch.source_git_state,
            batch.imported_at,
            batch.effective_at,
            batch.portfolio_id,
            batch.manifest_sha256,
            batch.quality_report_json,
            not saved,
        )

    @staticmethod
    def _parse_opening(path: Path, effective: datetime) -> tuple[OpeningPosition, ...]:
        out = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for n, row in enumerate(csv.DictReader(f), 2):
                h = hashlib.sha256(
                    (json.dumps(row, ensure_ascii=False, sort_keys=True) + str(n)).encode()
                ).hexdigest()
                out.append(
                    OpeningPosition(
                        row["ts_code"].strip(),
                        int(row["quantity"]),
                        Decimal(row["cost_price"]),
                        effective,
                        h,
                    )
                )
        return tuple(out)

    @staticmethod
    def _parse_history(
        path: Path, snapshot: datetime, source_hash: str
    ) -> tuple[ImportedHistoricalPosition, ...]:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return tuple(
                ImportedHistoricalPosition(
                    snapshot,
                    row["ts_code"].strip(),
                    int(row["quantity"]),
                    Decimal(row["cost_price"]),
                    (row.get("buy_date") or "").strip() or None,
                    source_hash,
                    json.dumps(row, ensure_ascii=False, sort_keys=True),
                )
                for row in csv.DictReader(f)
            )
