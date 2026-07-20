from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Thread
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestRequest,
    StrategyGroup,
)
from backend.app.features.backtests.repository import BacktestResultConflict, SqlBacktestRepository
from backend.app.features.runs.repository import RunRepository
from backend.app.contracts.runs import RunKind
from backend.app.infrastructure.persistence.models import Base
from backend.tests.features.backtests.fakes import MemoryArtifactRepository


@pytest.fixture
def fixed_result() -> BacktestExperimentResult:
    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=datetime(2023, 1, 2, tzinfo=UTC).date(),
        end_date=datetime(2023, 1, 4, tzinfo=UTC).date(),
        initial_cash=Decimal("150000"),
        groups=[StrategyGroup.A, StrategyGroup.B],
        out_of_sample_start=datetime(2023, 1, 3, tzinfo=UTC).date(),
    )
    groups = tuple(
        BacktestGroupResult(
            group=group,
            data_grade=DataGrade.RESEARCH,
            llm_grade=LlmGrade.NOT_USED if group is StrategyGroup.A else LlmGrade.RECONSTRUCTED,
            input_manifest_hash="manifest-1",
            equity_curve=[
                {"trade_date": "2023-01-02", "equity": "150000"},
                {"trade_date": "2023-01-03", "equity": "150100"},
            ],
            trades=[
                {
                    "order_id": f"{group.value}-trade-1",
                    "trade_date": "2023-01-03",
                    "security_id": "600000.SH",
                    "side": "buy",
                    "quantity": "100",
                    "price": "10.01",
                    "fee": "5",
                },
                {
                    "order_id": f"{group.value}-trade-2",
                    "trade_date": "2023-01-04",
                    "security_id": "600000.SH",
                    "side": "sell",
                    "quantity": "100",
                    "price": "10.20",
                    "fee": "5.20",
                },
            ],
            rejected_attempts=[
                {
                    "order_id": f"{group.value}-reject-1",
                    "trade_date": "2023-01-03",
                    "reason_code": "LIMIT_UP_LOCKED",
                }
            ],
            metrics={"profit_factor": "1.23", "closed_trade_count": 1},
            metric_details={
                "values": {"profit_factor": {"value": "1.23", "diagnostic": None}},
                "acceptance_gates": [{"name": "net_profit_factor", "passed": False}],
            },
            warnings=["research_only"],
        )
        for group in (StrategyGroup.A, StrategyGroup.B)
    )
    return BacktestExperimentResult(
        request=request,
        input_manifest_hash="experiment-manifest-1",
        groups=groups,
        warnings=["research_only"],
    )


@pytest.fixture
def repository(postgres_engine: Engine) -> SqlBacktestRepository:
    from backend.app.features.backtests.db_models import (
        BacktestCurvePointRow,
        BacktestGroupResultRow,
        BacktestRejectedAttemptRow,
        BacktestResultRow,
        BacktestTradeRow,
    )

    tables = (
        BacktestResultRow.__table__,
        BacktestGroupResultRow.__table__,
        BacktestCurvePointRow.__table__,
        BacktestTradeRow.__table__,
        BacktestRejectedAttemptRow.__table__,
    )
    for table in tables:
        table.create(postgres_engine, checkfirst=True)
    with postgres_engine.begin() as connection:
        for table in reversed(tables):
            connection.execute(table.delete())
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False, class_=Session)
    return SqlBacktestRepository(sessions)


def test_round_trip_preserves_research_result_and_audit_records(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000001")

    repository.save_result(run_id, fixed_result, created_at=datetime(2026, 7, 19, tzinfo=UTC))

    restored = repository.fetch_result(run_id)
    summary = repository.fetch_summary(run_id)
    assert restored is not None
    assert restored.request.initial_cash == Decimal("150000")
    assert [item.llm_grade.value for item in restored.groups] == ["not_used", "reconstructed"]
    assert restored.groups[0].metric_details["acceptance_gates"] == [
        {"name": "net_profit_factor", "passed": False}
    ]
    assert restored.groups[0].trades[1]["price"] == "10.20"
    assert restored.groups[0].rejected_attempts[0]["reason_code"] == "LIMIT_UP_LOCKED"
    assert summary.created_at == datetime(2026, 7, 19, tzinfo=UTC)
    assert summary.groups[1].llm_grade is LlmGrade.RECONSTRUCTED


def test_result_pages_use_deterministic_cursors(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000002")
    repository.save_result(run_id, fixed_result, created_at=datetime(2026, 7, 19, tzinfo=UTC))

    first = repository.page_trades(run_id, StrategyGroup.A, limit=1)
    second = repository.page_trades(run_id, StrategyGroup.A, limit=1, cursor=first.next_cursor)

    assert [item["order_id"] for item in first.items] == ["A-trade-1"]
    assert first.next_cursor == "A-trade-2"
    assert [item["order_id"] for item in second.items] == ["A-trade-2"]
    assert second.next_cursor is None


def test_same_run_id_rejects_different_research_evidence(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000003")
    repository.save_result(run_id, fixed_result, created_at=datetime(2026, 7, 19, tzinfo=UTC))
    changed = fixed_result.model_copy(update={"input_manifest_hash": "different-manifest"})

    with pytest.raises(BacktestResultConflict):
        repository.save_result(run_id, changed, created_at=datetime(2026, 7, 19, tzinfo=UTC))


def test_publish_result_commits_result_and_artifact_together(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000004")
    artifacts = MemoryArtifactRepository()

    repository.publish_result(run_id, fixed_result, artifacts)

    assert repository.fetch_result(run_id) == fixed_result
    assert len(artifacts.refs) == 1


@pytest.mark.postgres
def test_requeued_claim_cannot_publish_a_backtest_result_or_artifact(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
    postgres_engine: Engine,
) -> None:
    Base.metadata.create_all(postgres_engine)
    sessions = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    now = datetime(2026, 7, 20, tzinfo=UTC)
    with sessions.begin() as session:
        session.execute(text("TRUNCATE TABLE run_artifacts, run_events, runs CASCADE"))
        run = RunRepository(session).submit(RunKind.BACKTEST, {}, None, now)
        claimed = RunRepository(session).claim_next(now, "old-worker", "old-token")
        assert claimed is not None
        recovered_at = now + timedelta(minutes=1)
        RunRepository(session).requeue_stale(recovered_at, recovered_at)
        replacement = RunRepository(session).claim_next(recovered_at, "new-worker", "new-token")
        assert replacement is not None

    artifacts = MemoryArtifactRepository()
    with pytest.raises(RuntimeError, match="BACKTEST_PUBLICATION_FENCED"):
        repository.publish_result(
            run.id,
            fixed_result,
            artifacts,
            claim_owner="old-worker",
            claim_token="old-token",
        )

    assert repository.fetch_result(run.id) is None
    assert artifacts.refs == {}


def test_concurrent_duplicate_result_publication_is_idempotent(
    repository: SqlBacktestRepository,
    fixed_result: BacktestExperimentResult,
) -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000005")
    barrier = Barrier(2)

    class CoordinatedRepository(SqlBacktestRepository):
        def _save_result(
            self,
            session: Session,
            run_id: UUID,
            result: BacktestExperimentResult,
            created_at: datetime | None,
        ) -> bool:
            barrier.wait()
            return super()._save_result(session, run_id, result, created_at)

    repository = CoordinatedRepository(repository._session_factory)
    errors: list[Exception] = []

    def save() -> None:
        try:
            barrier.wait()
            repository.save_result(run_id, fixed_result)
        except Exception as exc:  # The assertion below reports unexpected persistence failures.
            errors.append(exc)

    first = Thread(target=save)
    second = Thread(target=save)
    first.start()
    second.start()
    first.join()
    second.join()

    assert errors == []
    assert repository.fetch_result(run_id) == fixed_result
