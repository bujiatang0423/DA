import hashlib
import json
from datetime import datetime
from pathlib import Path

from backend.app.features.legacy_import.service import LegacyImportService


class Repo:
    def __init__(self) -> None:
        self.calls = []

    def save(self, batch, raw_files, positions, historical_snapshots):
        self.calls.append((batch, raw_files, positions, historical_snapshots))
        return len(self.calls) == 1


def test_import_is_read_only_hashed_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    holdings = source / "data" / "holdings"
    history = holdings / "历史持仓"
    history.mkdir(parents=True)
    (holdings / "持仓.csv").write_text("ts_code,quantity,cost_price\nAAA,10,12.5\n", encoding="utf-8-sig")
    archive = history / "2025-01-01_100000.csv"
    archive.write_text("ts_code,quantity,cost_price,buy_date\nAAA,8,11,2024-01-01\n", encoding="utf-8-sig")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (history / "index.json").write_text(json.dumps([{"archive": archive.name, "sha256": digest}]), encoding="utf-8")
    before = (holdings / "持仓.csv").read_bytes()
    repo = Repo()
    effective = datetime(2026, 1, 1).astimezone()
    service = LegacyImportService(tmp_path / "imports", repo)
    first = service.import_source(source_root=source, portfolio_id="p", effective_at=effective)
    second = service.import_source(source_root=source, portfolio_id="p", effective_at=effective)
    assert first.batch_id == second.batch_id
    assert second.idempotent is True
    assert first.effective_at == effective
    assert (holdings / "持仓.csv").read_bytes() == before
    assert first.manifest_sha256
    assert len(repo.calls[0][2]) == 1
    assert repo.calls[0][2][0].origin.value == "legacy_opening_balance"
    assert repo.calls[0][3][0].snapshot_at.year == 2025
    assert not hasattr(repo.calls[0][3][0], "trade_id")
