from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.contracts.grades import DataGrade
from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.execution import ExecutionSimulator
from backend.app.features.backtests.ports import (
    BacktestDecisionPort,
    BacktestSnapshotPort,
    BacktestTradingDayPort,
)
from backend.app.features.backtests.strict_execution import (
    CertifiedExecutionInputs,
    StrictBacktestExecutionPort,
    StrictExecutionSimulator,
)
from backend.app.infrastructure.market.strict_backtest_data import (
    SqlAlchemyTradingCalendar,
    StrictBacktestSnapshotAdapter,
)


def build_strict_backtest_engine(
    trading_days: BacktestTradingDayPort,
    warehouse: BacktestSnapshotPort,
    decision_port: BacktestDecisionPort,
) -> BacktestEngine:
    """Build the strict engine for later Task 7 application and API composition."""
    simulator = StrictExecutionSimulator(
        ExecutionSimulator(),
        CertifiedExecutionInputs(warehouse),
    )
    execution_port = StrictBacktestExecutionPort(simulator)
    return BacktestEngine(
        trading_days,
        StrictBacktestSnapshotAdapter(warehouse),
        decision_port,
        execution_port,
        data_grade=DataGrade.PIT_VERIFIED,
    )


def build_sqlalchemy_strict_backtest_engine(
    *,
    session: Session,
    warehouse: BacktestSnapshotPort,
    decision_port: BacktestDecisionPort,
    exchange: str = "SSE",
) -> BacktestEngine:
    """Compose a strict engine from PIT SQL data with no permissive data fallback."""
    return build_strict_backtest_engine(
        SqlAlchemyTradingCalendar(
            session,
            exchange=exchange,
        ),
        warehouse,
        decision_port,
    )
