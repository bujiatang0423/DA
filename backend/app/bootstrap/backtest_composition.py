from __future__ import annotations

from datetime import datetime

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
from backend.app.infrastructure.market.strict_backtest_data import (
    SqlAlchemyHistoricalDailyBars,
    SqlAlchemyTradingCalendar,
    StrictBacktestSnapshotAdapter,
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
    calendar_as_of_time: datetime,
    exchange: str = "SSE",
) -> BacktestEngine:
    """Compose a strict engine from PIT SQL data with no permissive data fallback."""
    return build_strict_backtest_engine(
        SqlAlchemyTradingCalendar(
            session,
            as_of_time=calendar_as_of_time,
            exchange=exchange,
        ),
        warehouse,
        decision_port,
        SqlAlchemyHistoricalDailyBars(session),
        session,
    )
