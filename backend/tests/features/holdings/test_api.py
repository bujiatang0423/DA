from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.contracts.runs import RunKind, RunLinks, RunRef, RunStatus
from backend.app.core.portfolio.analysis import HoldingAnalysisService as LegacyHoldingService
from backend.app.core.portfolio.models import PositionOrigin
from backend.app.features.holdings.jobs import HoldingAnalysisJobHandler
from backend.app.features.holdings.router import build_router
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
    repository: FakeHoldingAnalysisRepository,
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
) -> TestClient:
    repository = FakeHoldingAnalysisRepository()
    router = build_router(
        LegacyHoldingService(reader),
        repository=repository,
        portfolio_reader=reader,
        portfolio_writer=writer,
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
