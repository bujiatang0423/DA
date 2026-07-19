from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from backend.app.bootstrap.application import create_app
from backend.app.features.legacy_import.module import build_legacy_import_feature
from backend.app.features.legacy_import.web_service import LegacyImportWebService


class Repository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}
        self._manifests: set[str] = set()

    def save(self, batch: Any, raw_files: Any, positions: Any, snapshots: Any) -> bool:  # noqa: ANN401
        if batch.manifest_sha256 in self._manifests:
            return False
        self._manifests.add(batch.manifest_sha256)
        self._rows[batch.batch_id] = {
            "batch_id": batch.batch_id,
            "manifest_sha256": batch.manifest_sha256,
            "raw_file_count": len(raw_files),
            "opening_position_count": len(positions),
            "historical_snapshot_count": len(snapshots),
            "idempotent": False,
        }
        return True

    def get_summary(self, batch_id: str) -> dict[str, object] | None:
        return self._rows.get(batch_id)


def _source(root: Path) -> None:
    holdings = root / "broker-a" / "data" / "holdings"
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


def _current_only_source(root: Path, *, empty_history: bool) -> None:
    holdings = root / "broker-a" / "data" / "holdings"
    holdings.mkdir(parents=True)
    (holdings / "持仓.csv").write_text(
        "ts_code,quantity,cost_price\nAAA,10,12.5\n", encoding="utf-8-sig"
    )
    if empty_history:
        (holdings / "历史持仓").mkdir()


def test_import_api_only_accepts_configured_sources_and_requires_confirmation(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    _source(allowed)
    repository = Repository()
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=lambda: repository,
    )
    client = TestClient(create_app((build_legacy_import_feature(service),)))
    payload = {
        "source_id": "broker-a",
        "portfolio_id": "main",
        "effective_at": datetime(2026, 7, 19, 9, 0, tzinfo=UTC).isoformat(),
    }

    assert client.get("/api/v1/legacy-imports/sources").json() == {
        "items": [{"source_id": "broker-a", "label": "broker-a"}]
    }
    assert (
        client.post(
            "/api/v1/legacy-imports/preview", json={**payload, "source_id": "../x"}
        ).status_code
        == 404
    )
    preview = client.post("/api/v1/legacy-imports/preview", json=payload)
    assert preview.status_code == 200
    assert str(allowed) not in preview.text

    assert (
        client.post(
            "/api/v1/legacy-imports/confirm",
            json={**payload, "confirmation_token": "invalid-token-which-is-long-enough"},
        ).status_code
        == 409
    )
    confirmed = client.post(
        "/api/v1/legacy-imports/confirm",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert confirmed.status_code == 200
    batch_id = confirmed.json()["batch_id"]
    assert client.get(f"/api/v1/legacy-imports/{batch_id}").json()["raw_file_count"] == 2


@pytest.mark.parametrize(
    ("relative_path", "outside_name"),
    (
        ("持仓.csv", "outside-current.csv"),
        ("历史持仓/2025-01-01_100000.csv", "outside-history.csv"),
        ("历史持仓/index.json", "outside-index.json"),
    ),
)
def test_import_api_rejects_selected_file_symlinked_outside_selected_source(
    tmp_path: Path,
    relative_path: str,
    outside_name: str,
) -> None:
    allowed = tmp_path / "allowed"
    _source(allowed)
    target = allowed / "broker-a" / "data" / "holdings" / relative_path
    outside = tmp_path / outside_name
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=Repository,
    )
    client = TestClient(create_app((build_legacy_import_feature(service),)))

    response = client.post(
        "/api/v1/legacy-imports/preview",
        json={
            "source_id": "broker-a",
            "portfolio_id": "main",
            "effective_at": datetime(2026, 7, 19, 9, 0, tzinfo=UTC).isoformat(),
        },
    )

    assert response.status_code == 409
    assert str(outside) not in response.text


@pytest.mark.parametrize("empty_history", (False, True))
def test_import_api_accepts_current_only_sources_with_optional_history(
    tmp_path: Path,
    empty_history: bool,
) -> None:
    allowed = tmp_path / "allowed"
    _current_only_source(allowed, empty_history=empty_history)
    service = LegacyImportWebService(
        imports_root=tmp_path / "imports",
        source_roots=(allowed,),
        repository_factory=Repository,
    )
    client = TestClient(create_app((build_legacy_import_feature(service),)))
    payload = {
        "source_id": "broker-a",
        "portfolio_id": "main",
        "effective_at": datetime(2026, 7, 20, 9, 0, tzinfo=UTC).isoformat(),
    }

    assert client.get("/api/v1/legacy-imports/sources").json() == {
        "items": [{"source_id": "broker-a", "label": "broker-a"}]
    }
    preview = client.post("/api/v1/legacy-imports/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["historical_position_count"] == 0
    assert preview.json()["source_file_count"] == 1

    confirmed = client.post(
        "/api/v1/legacy-imports/confirm",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["raw_file_count"] == 1
    assert confirmed.json()["historical_snapshot_count"] == 0
