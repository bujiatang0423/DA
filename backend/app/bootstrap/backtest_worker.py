from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from backend.app.bootstrap.backtest_composition import build_sqlalchemy_strict_backtest_engine
from backend.app.bootstrap.settings import Settings
from backend.app.core.market.strategy_inputs import StrategyInputBuilder
from backend.app.core.market.pit_models import SnapshotScope
from backend.app.core.strategy.service import V212StrategyEngine
from backend.app.features.backtests.decision import MaskedV212BacktestDecisionPort
from backend.app.features.backtests.experiments import ExperimentRunner
from backend.app.features.backtests.jobs import BacktestJobHandler
from backend.app.features.backtests.models import BacktestExperimentResult, BacktestRequest
from backend.app.features.backtests.ports import BacktestSnapshotPort, BacktestSnapshotQualityError
from backend.app.features.backtests.repository import SqlBacktestRepository
from backend.app.features.backtests.service import BacktestService
from backend.app.features.runs.artifacts import SqlArtifactRepository
from backend.app.infrastructure.market.build import build_strict_pit_warehouse
from backend.app.infrastructure.market.strict_backtest_data import SqlAlchemyTradingCalendar


class BacktestWorkerConfigurationError(ValueError):
    """Raised when the strict PIT-only backtest worker cannot be safely composed."""


@dataclass(frozen=True)
class SqlStrictBacktestRunner:
    """Build one strict SQL engine per job, keeping no database session between jobs."""

    sessions: sessionmaker[Session]
    approval_secret: str

    def run(self, request: BacktestRequest) -> BacktestExperimentResult:
        with self.sessions() as session:
            warehouse = build_strict_pit_warehouse(
                session=session,
                approval_secret=self.approval_secret,
            )
            decision = MaskedV212BacktestDecisionPort(
                StrategyInputBuilder(),
                V212StrategyEngine(),
            )
            self._verify_first_decision_snapshot(session, warehouse, request)
            engine = build_sqlalchemy_strict_backtest_engine(
                session=session,
                warehouse=warehouse,
                decision_port=decision,
            )
            return ExperimentRunner(engine).run(request)

    @staticmethod
    def _verify_first_decision_snapshot(
        session: Session,
        warehouse: BacktestSnapshotPort,
        request: BacktestRequest,
    ) -> None:
        days = SqlAlchemyTradingCalendar(session, exchange="SSE").between(
            request.start_date,
            request.end_date,
        )
        if len(days) < 2:
            raise BacktestSnapshotQualityError()
        as_of_time = datetime.combine(days[0], time(15, 30), ZoneInfo("Asia/Shanghai"))
        scope = SnapshotScope.backtest(
            (),
            datetime.combine(request.start_date, time.min, ZoneInfo("Asia/Shanghai")),
        )
        snapshot = warehouse.snapshot(as_of_time=as_of_time, scope=scope)
        if snapshot.quality.has_errors:
            raise BacktestSnapshotQualityError()


def build_backtest_job_handler(
    settings: Settings,
    sessions: sessionmaker[Session],
) -> BacktestJobHandler:
    """Compose a backtest handler exclusively from certified SQL PIT dependencies."""
    approval_secret = settings.pit_approval_secret
    if approval_secret is None or len(approval_secret) < 32:
        raise BacktestWorkerConfigurationError(
            "PIT approval secret with at least 32 characters is required"
        )
    return BacktestJobHandler(
        BacktestService(
            SqlStrictBacktestRunner(sessions, approval_secret),
            SqlBacktestRepository(sessions),
            SqlArtifactRepository(sessions, settings.artifact_root),
        )
    )
