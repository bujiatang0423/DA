from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.features.legacy_import.web_service import (
    LegacyImportConfirmationError,
    LegacyImportWebService,
)


class Repository:
    def __init__(self) -> None:
        self.manifests: set[str] = set()
        self.batches: dict[str, dict[str, object]] = {}

    def save(self, batch: Any, raw_files: Any, positions: Any, snapshots: Any) -> bool:  # noqa: ANN401
        del positions, snapshots
        if batch.manifest_sha256 in self.manifests:
            return False
        self.manifests.add(batch.manifest_sha256)
        self.batches[batch.batch_id] = {
            "batch_id": batch.batch_id,
            "manifest_sha256": batch.manifest_sha256,
            "portfolio_id": batch.portfolio_id,
            "effective_at": batch.effective_at,
            "raw_file_count": len(raw_files),
            "opening_position_count": 1,
            "historical_snapshot_count": 1,
            "idempotent": False,
        }
        return True

    def get_summary(self, batch_id: str) -> dict[str, object] | None:
        return self.batches.get(batch_id)


def _source(root: Path, name: str = "broker-a") -> Path:
    source = root / name
    holdings = source / "data" / "holdings"
    history = holdings / "历史持仓"
    history.mkdir(parents=True)
    (holdings / "持仓.csv").write_text(
        "ts_code,quantity,cost_price\nAAA,10,12.5\n", encoding="utf-8-sig"
    )
    archive = history / "2025-01-01_100000.csv"
    archive.write_text(
        "ts_code,quantity,cost_price,buy_date\nAAA,8,11,2024-01-01\n", encoding="utf-8-sig"
    )
    (history / "index.json").write_text(
        json.dumps(
            [{"archive": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]
        ),
        encoding="utf-8",
    )
    return source


def test_only_configured_immediate_sources_are_listed_and_resolved(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    source = _source(allowed)
    escaped = _source(tmp_path / "outside", "escape")
    (allowed / "linked-outside").symlink_to(escaped, target_is_directory=True)
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=lambda: Repository(),
    )

    sources = service.sources()

    assert [(item.source_id, item.label) for item in sources] == [("broker-a", "broker-a")]
    assert service.resolve_source("broker-a") == source.resolve()
    with pytest.raises(KeyError):
        service.resolve_source("../outside/escape")
    with pytest.raises(KeyError):
        service.resolve_source("linked-outside")


def test_preview_needs_a_single_use_confirmation_before_freezing(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    _source(allowed)
    repository = Repository()
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=lambda: repository,
    )
    effective_at = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)

    preview = service.preview("broker-a", "main", effective_at)

    assert preview.current_position_count == 1
    assert preview.historical_position_count == 1
    assert preview.quality_tags == ()
    assert not (tmp_path / "imports" / "raw").exists()
    with pytest.raises(LegacyImportConfirmationError):
        service.confirm("invalid", "broker-a", "main", effective_at)

    result = service.confirm(preview.confirmation_token, "broker-a", "main", effective_at)

    assert result.idempotent is False
    assert (tmp_path / "imports" / result.batch_id / "raw" / "current" / "持仓.csv").is_file()
    with pytest.raises(LegacyImportConfirmationError):
        service.confirm(preview.confirmation_token, "broker-a", "main", effective_at)


def test_confirmation_imports_the_preview_snapshot_after_source_changes(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    source = _source(allowed)
    repository = Repository()
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=lambda: repository,
    )
    effective_at = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    current = source / "data" / "holdings" / "持仓.csv"
    preview_bytes = current.read_bytes()
    preview = service.preview("broker-a", "main", effective_at)
    current.write_text("ts_code,quantity,cost_price\nAAA,99,99\n", encoding="utf-8-sig")

    result = service.confirm(preview.confirmation_token, "broker-a", "main", effective_at)

    frozen = tmp_path / "imports" / result.batch_id / "raw" / "current" / "持仓.csv"
    assert frozen.read_bytes() == preview_bytes


def test_confirmation_returns_the_existing_batch_as_idempotent(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    _source(allowed)
    repository = Repository()
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=lambda: repository,
    )
    effective_at = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)

    first = service.confirm(
        service.preview("broker-a", "main", effective_at).confirmation_token,
        "broker-a",
        "main",
        effective_at,
    )
    second = service.confirm(
        service.preview("broker-a", "main", effective_at).confirmation_token,
        "broker-a",
        "main",
        effective_at,
    )

    assert second.batch_id == first.batch_id
    assert second.idempotent is True
    assert service.result(first.batch_id).raw_file_count == 2
