import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.core.portfolio.models import OpeningPosition
from backend.app.features.legacy_import import cli
from backend.app.features.legacy_import.service import (
    ImportedBatch,
    ImportedHistoricalPosition,
    ImportedRawFile,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.manifests: set[str] = set()

    def save(
        self,
        batch: ImportedBatch,
        raw_files: tuple[ImportedRawFile, ...],
        positions: tuple[OpeningPosition, ...],
        snapshots: tuple[ImportedHistoricalPosition, ...],
    ) -> bool:
        del raw_files, positions, snapshots
        if batch.manifest_sha256 in self.manifests:
            return False
        self.manifests.add(batch.manifest_sha256)
        return True


class SessionFactory:
    @contextmanager
    def begin(self) -> Iterator[object]:
        yield object()


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "legacy"
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
        json.dumps([{"archive": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]),
        encoding="utf-8",
    )
    return source


def test_cli_requires_source_root_effective_at_and_portfolio() -> None:
    parsed = cli.build_parser().parse_args(
        [
            "--source-root",
            "/read-only/source",
            "--effective-at",
            "2026-07-17T09:00:00+08:00",
            "--portfolio-id",
            "main",
        ]
    )

    assert parsed.source_root == "/read-only/source"
    assert parsed.effective_at.endswith("+08:00")
    assert parsed.portfolio_id == "main"


def test_cli_import_is_idempotent_and_does_not_modify_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    source_hashes = {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    repository = MemoryRepository()
    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(database_url="memory://test"))
    monkeypatch.setattr(cli, "build_engine", lambda database_url: object())
    monkeypatch.setattr(cli, "build_session_factory", lambda engine: SessionFactory())
    monkeypatch.setattr(cli, "SqlLegacyRepository", lambda session: repository)
    arguments = [
        "da-legacy-import",
        "--source-root",
        str(source),
        "--effective-at",
        datetime(2026, 7, 17, 9, 0, tzinfo=UTC).isoformat(),
        "--portfolio-id",
        "main",
        "--imports-root",
        str(tmp_path / "imports"),
    ]
    monkeypatch.setattr(sys, "argv", arguments)

    assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main() == 0
    second = json.loads(capsys.readouterr().out)

    assert first["batch_id"] == second["batch_id"]
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert source_hashes == {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }


def test_da_runtime_does_not_reference_la_workspace_or_pythonpath() -> None:
    project_root = Path(__file__).resolve().parents[4]
    forbidden = ("/Users/bujiatang/workspace/LA", "workspace.LA", "PYTHONPATH")
    violations = [
        path
        for path in (project_root / "backend" / "app").rglob("*.py")
        if any(token in path.read_text(encoding="utf-8") for token in forbidden)
    ]

    assert violations == []
