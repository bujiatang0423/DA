from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunLinks, RunRef, RunStatus
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    SecurityObservation,
    TemporalRecord,
)
from backend.app.core.portfolio.analysis import HoldingAnalysisService as LegacyHoldingService
from backend.app.core.portfolio.models import PositionOrigin
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.holdings.repository import (
    HoldingAnalysisItemRow,
    HoldingAnalysisRepository,
    HoldingResultRow,
    SqlHoldingAnalysisRepository,
)
from backend.app.features.holdings.router import LegacyImportProvenance, build_router
from backend.app.features.holdings.service import HoldingAnalysisService
from backend.app.infrastructure.persistence.portfolio_repository import BackdatedPortfolioMutation
from backend.app.infrastructure.tasks.handlers import JobContext
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate
from backend.tests.features.holdings.factories import holding_analysis_result, portfolio_snapshot
from backend.tests.features.holdings.fakes import (
    FakeClock,
    FakeHoldingAnalysisRepository,
    FakePortfolioReader,
    FakePortfolioWriter,
)
from backend.tests.features.holdings.test_service import build_service


@dataclass
class RecordingSubmitter:
    calls: list[tuple[RunKind, dict[str, object], str | None, datetime]] = field(
        default_factory=list
    )

    def __call__(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef:
        self.calls.append((kind, payload, idempotency_key, submitted_at))
        run_id = "00000000-0000-0000-0000-000000000008"
        return RunRef(
            run_id=run_id,
            kind=kind,
            status=RunStatus.QUEUED,
            submitted_at=submitted_at,
            links=RunLinks(
                self=f"/api/v1/runs/{run_id}",
                artifacts=f"/api/v1/runs/{run_id}/artifacts",
            ),
        )


@dataclass
class RecordingAnalysisService:
    run_ids: list[str] = field(default_factory=list)

    def run(self, command: object) -> object:
        self.run_ids.append(str(command.run_id))
        return holding_analysis_result(str(command.run_id))


def holding_client(
    submitter: RecordingSubmitter,
    repository: HoldingAnalysisRepository,
) -> TestClient:
    reader = FakePortfolioReader(portfolio_snapshot())
    router = build_router(
        LegacyHoldingService(reader),
        submitter,
        repository,
        clock=FakeClock(reader.snapshot_value.as_of_time),
    )
    return TestClient(create_app((FeatureModule("holdings", router, ()),)))


def portfolio_client(
    reader: FakePortfolioReader,
    writer: FakePortfolioWriter,
    import_provenance_reader: object | None = None,
) -> TestClient:
    repository = FakeHoldingAnalysisRepository()
    router = build_router(
        LegacyHoldingService(reader),
        repository=repository,
        portfolio_reader=reader,
        portfolio_writer=writer,
        import_provenance_reader=import_provenance_reader,
        clock=FakeClock(reader.snapshot_value.as_of_time),
    )
    return TestClient(create_app((FeatureModule("holdings", router, ()),)))


def test_async_submission_payload_is_accepted_unchanged_by_worker() -> None:
    submitter = RecordingSubmitter()
    repository = FakeHoldingAnalysisRepository()
    client = holding_client(submitter, repository)

    response = client.post(
        "/api/v1/holding-analyses",
        headers={"Idempotency-Key": "holding-20260717"},
        json={
            "portfolio_id": "default",
            "as_of_time": "2026-07-17T15:00:00+08:00",
        },
    )

    assert response.status_code == 202
    assert response.headers["location"].endswith(response.json()["run_id"])
    kind, payload, key, submitted_at = submitter.calls[0]
    assert kind is RunKind.HOLDING_ANALYSIS
    assert key == "holding-20260717"
    assert submitted_at == portfolio_snapshot().as_of_time
    assert set(payload) == {"portfolio_id", "as_of_time"}

    service = RecordingAnalysisService()
    handler = HoldingAnalysisJobHandler(service)
    heartbeats: list[tuple[str, int]] = []
    handler(
        JobContext(
            run_id=UUID(response.json()["run_id"]),
            payload=payload,
            heartbeat=lambda stage, progress: heartbeats.append((stage, progress)),
        )
    )
    assert service.run_ids == [response.json()["run_id"]]
    assert heartbeats == [("evaluating_holdings", 20), ("persisted", 100)]


def test_latest_and_result_return_persisted_advice() -> None:
    submitter = RecordingSubmitter()
    result = holding_analysis_result("holding-api-result")
    repository = FakeHoldingAnalysisRepository([result])
    client = holding_client(submitter, repository)

    latest = client.get("/api/v1/holding-analyses/latest?portfolio_id=default")
    by_run = client.get(f"/api/v1/holding-analyses/{result.run_id}")

    assert latest.status_code == 200
    assert by_run.status_code == 200
    assert latest.json()["run_id"] == result.run_id
    assert by_run.json()["manifest_hash"] == result.manifest_hash
    assert latest.json()["summary"]["market_state"] == "neutral"
    assert latest.json()["summary"]["portfolio_risk_pct"] == "1.25"
    assert latest.json()["items"][0]["factors"]["s"] == "62.5"
    assert latest.json()["items"][0]["factors"]["percentile_rank"] == "0.80"
    assert latest.json()["items"][0]["r_multiple"] == "1.50"
    assert latest.json()["items"][0]["evidence_refs"] == ["market-close:600000.SH:2026-07-17"]


@pytest.mark.postgres
def test_restarted_handler_and_api_read_normalized_audit_items_from_postgresql(
    postgres_engine: Engine,
) -> None:
    HoldingResultRow.__table__.create(postgres_engine, checkfirst=True)
    HoldingAnalysisItemRow.__table__.create(postgres_engine, checkfirst=True)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service, command, warehouse, portfolios, builder, strategy, _ = build_service()
    run_id = uuid4()
    artifact_hash = "a" * 64
    warehouse.snapshot_value = replace(
        warehouse.snapshot_value,
        security_observations=(
            SecurityObservation(
                "000001.SZ",
                (
                    TemporalRecord(
                        record_id="holding-evidence",
                        kind=DataKind.DAILY_BAR_RAW,
                        entity_id="000001.SZ",
                        event_time=command.as_of_time,
                        observed_at=command.as_of_time,
                        available_at=command.as_of_time,
                        source_artifact_hash=artifact_hash,
                        payload={},
                    ),
                ),
            ),
        ),
        lineage=(LineageRef("holding-evidence-batch", "pit", artifact_hash),),
    )
    analysis_service = HoldingAnalysisService(
        warehouse,
        portfolios,
        builder,
        strategy,
        SqlHoldingAnalysisRepository(sessions),
    )
    context = JobContext(
        run_id=run_id,
        payload={
            "portfolio_id": command.portfolio_id,
            "as_of_time": command.as_of_time.isoformat(),
        },
        heartbeat=lambda _stage, _progress: None,
    )

    HoldingAnalysisJobHandler(analysis_service)(context)
    HoldingAnalysisJobHandler(analysis_service)(context)

    restarted_repository = SqlHoldingAnalysisRepository(sessions)
    client = holding_client(RecordingSubmitter(), restarted_repository)
    response = client.get(f"/api/v1/holding-analyses/{run_id}")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["security_id"] == "000001.SZ"
    assert items[0]["reason_codes"] == ["ELIGIBLE"]
    assert items[0]["quality_codes"] == []
    assert items[0]["evidence_refs"] == [f"pit:daily_bar_raw:{artifact_hash}"]
    with sessions() as session:
        child_rows = session.query(HoldingAnalysisItemRow).filter_by(run_id=str(run_id)).all()
    assert [(row.item_index, row.security_id) for row in child_rows] == [(0, "000001.SZ")]


def test_latest_at_returns_only_an_analysis_for_the_requested_decision_time() -> None:
    submitter = RecordingSubmitter()
    result = holding_analysis_result("holding-api-exact")
    repository = FakeHoldingAnalysisRepository([result])
    client = holding_client(submitter, repository)

    exact = client.get(
        "/api/v1/holding-analyses/latest",
        params={"portfolio_id": "default", "as_of_time": result.as_of_time.isoformat()},
    )
    other_time = client.get(
        "/api/v1/holding-analyses/latest",
        params={"portfolio_id": "default", "as_of_time": "2026-07-19T09:00:00Z"},
    )

    assert exact.status_code == 200
    assert exact.json()["run_id"] == result.run_id
    assert other_time.status_code == 404


def test_positions_preserve_legacy_origin_and_unknown_book() -> None:
    snapshot = portfolio_snapshot()
    legacy_lot = replace(
        snapshot.lots[0],
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        strategy_book=None,
    )
    snapshot = replace(snapshot, lots=(legacy_lot,))
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(snapshot)
    client = portfolio_client(reader, writer)

    response = client.get("/api/v1/portfolio/positions")

    assert response.status_code == 200
    position = response.json()["items"][0]
    assert position["origin"] == "legacy_opening_balance"
    assert position["strategy_book"] is None


def test_positions_return_only_server_verified_import_provenance() -> None:
    snapshot = portfolio_snapshot()
    legacy_lot = replace(
        snapshot.lots[0],
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        strategy_book=None,
        batch_id="batch-1",
    )
    reader = FakePortfolioReader(replace(snapshot, lots=(legacy_lot,)))
    writer = FakePortfolioWriter(reader.snapshot_value)

    def provenance(batch_id: str) -> LegacyImportProvenance | None:
        if batch_id != "batch-1":
            return None
        return LegacyImportProvenance(
            batch_id="batch-1",
            manifest_sha256="a" * 64,
            portfolio_id="default",
            effective_at=reader.snapshot_value.as_of_time,
        )

    client = portfolio_client(reader, writer, provenance)
    response = client.get(
        f"/api/v1/portfolio/positions?import_batch_id=batch-1&import_manifest_sha256={'a' * 64}"
    )

    assert response.status_code == 200
    assert response.json()["import_provenance"] == {
        "batch_id": "batch-1",
        "manifest_sha256": "a" * 64,
    }


def test_positions_reject_tampered_import_manifest_without_echoing_it() -> None:
    snapshot = portfolio_snapshot()
    legacy_lot = replace(
        snapshot.lots[0],
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        batch_id="batch-1",
    )
    reader = FakePortfolioReader(replace(snapshot, lots=(legacy_lot,)))
    writer = FakePortfolioWriter(reader.snapshot_value)
    client = portfolio_client(
        reader,
        writer,
        lambda _batch_id: LegacyImportProvenance(
            batch_id="batch-1",
            manifest_sha256="a" * 64,
            portfolio_id="default",
            effective_at=reader.snapshot_value.as_of_time,
        ),
    )

    response = client.get(
        "/api/v1/portfolio/positions?import_batch_id=batch-1&"
        "import_manifest_sha256=not-the-real-manifest"
    )

    assert response.status_code == 409
    assert "not-the-real-manifest" not in response.text


def test_position_correction_is_audited_and_optimistic() -> None:
    snapshot = portfolio_snapshot()
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(replace(snapshot, version=8))
    client = portfolio_client(reader, writer)

    response = client.put(
        "/api/v1/portfolio/positions",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "reason": "核对券商对账单后修正数量",
            "positions": [
                {
                    "security_id": "000001.SZ",
                    "quantity": 600,
                    "average_cost": "10.30",
                    "effective_at": "2026-07-17T15:00:00+08:00",
                }
            ],
        },
    )

    assert response.status_code == 200
    correction, expected_version, reason = writer.corrections[0]
    assert expected_version == 7
    assert reason == "核对券商对账单后修正数量"
    assert correction.lots[0].quantity == 600


def test_position_correction_preserves_unmentioned_holdings() -> None:
    snapshot = portfolio_snapshot()
    second_lot = replace(
        snapshot.lots[0],
        lot_id="lot-2",
        security_id="600000.SH",
        quantity=200,
        available_to_sell=200,
    )
    snapshot = replace(snapshot, lots=(*snapshot.lots, second_lot))
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(replace(snapshot, version=8))
    client = portfolio_client(reader, writer)

    response = client.put(
        "/api/v1/portfolio/positions",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "reason": "更正平安银行数量",
            "positions": [
                {
                    "security_id": "000001.SZ",
                    "quantity": 600,
                    "average_cost": "10.30",
                    "effective_at": "2026-07-17T15:00:00+08:00",
                }
            ],
        },
    )

    assert response.status_code == 200
    correction, _, _ = writer.corrections[0]
    assert {lot.security_id: lot.quantity for lot in correction.lots} == {
        "000001.SZ": 600,
        "600000.SH": 200,
    }


def test_manual_fill_uses_actual_execution_price_and_fee() -> None:
    snapshot = portfolio_snapshot()
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(replace(snapshot, version=8))
    client = portfolio_client(reader, writer)

    response = client.post(
        "/api/v1/portfolio/fills",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "security_id": "000001.SZ",
            "side": "sell",
            "quantity": 100,
            "price": "10.35",
            "fee": "5.00",
            "executed_at": "2026-07-17T09:31:00+08:00",
        },
    )

    assert response.status_code == 200
    command, expected_version = writer.manual_fills[0]
    assert expected_version == 7
    assert command.price == Decimal("10.35")
    assert command.fee == Decimal("5.00")


def test_missing_analysis_uses_feature_error_code() -> None:
    client = holding_client(RecordingSubmitter(), FakeHoldingAnalysisRepository())

    response = client.get("/api/v1/holding-analyses/missing-run")

    assert response.status_code == 404
    assert response.json()["code"] == "HOLDING_ANALYSIS_NOT_FOUND"


def test_position_version_conflict_uses_stable_error_code() -> None:
    snapshot = portfolio_snapshot()
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(
        snapshot,
        conflict=ConcurrentPortfolioUpdate("expected version 7, current 8"),
    )
    client = portfolio_client(reader, writer)

    response = client.put(
        "/api/v1/portfolio/positions",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "reason": "核对券商对账单后修正数量",
            "positions": [
                {
                    "security_id": "000001.SZ",
                    "quantity": 600,
                    "average_cost": "10.30",
                    "effective_at": "2026-07-17T15:00:00+08:00",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PORTFOLIO_VERSION_CONFLICT"


def test_backdated_portfolio_change_uses_a_stable_client_error() -> None:
    snapshot = portfolio_snapshot()
    reader = FakePortfolioReader(snapshot)
    writer = FakePortfolioWriter(snapshot, error=BackdatedPortfolioMutation("backdated"))
    client = portfolio_client(reader, writer)

    response = client.post(
        "/api/v1/portfolio/fills",
        json={
            "portfolio_id": "default",
            "expected_version": 7,
            "security_id": "000001.SZ",
            "side": "sell",
            "quantity": 100,
            "price": "10.35",
            "fee": "5.00",
            "executed_at": "2026-07-17T09:31:00+08:00",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "BACKDATED_PORTFOLIO_MUTATION"
