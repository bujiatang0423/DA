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
    HistoricalDailyBarReader,
    StrictBacktestExecutionPort,
    StrictExecutionSimulator,
)
from backend.app.infrastructure.market.strict_queries import (
    TemporalExecutionQueries,
    TemporalSecurityQueries,
)


def build_strict_backtest_engine(
    trading_days: BacktestTradingDayPort,
    warehouse: BacktestSnapshotPort,
    decision_port: BacktestDecisionPort,
    bars: HistoricalDailyBarReader,
    session: Session,
) -> BacktestEngine:
    """Build the strict engine for later Task 7 application and API composition."""
    simulator = StrictExecutionSimulator(
        ExecutionSimulator(),
        TemporalSecurityQueries(session),
        TemporalExecutionQueries(session),
    )
    execution_port = StrictBacktestExecutionPort(simulator, bars)
    return BacktestEngine(
        trading_days,
        warehouse,
        decision_port,
        execution_port,
        data_grade=DataGrade.PIT_VERIFIED,
    )
