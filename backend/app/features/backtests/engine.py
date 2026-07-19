from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import SnapshotScope
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.ledger import PortfolioLedger
from backend.app.features.backtests.execution import FilledAttempt
from backend.app.features.backtests.metrics import calculate_metrics
from backend.app.features.backtests.models import (
    BacktestGroupResult,
    BacktestRequest,
    OrderIntent,
    StrategyGroup,
)
from backend.app.features.backtests.ports import (
    BacktestDecision,
    BacktestDecisionContext,
    BacktestDecisionPort,
    BacktestExecutionPort,
    BacktestSnapshotPort,
    BacktestTradingDayPort,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class BacktestEngine:
    """Deterministic event loop; execution adapters can be injected by callers."""

    def __init__(
        self,
        trading_days: BacktestTradingDayPort,
        warehouse: BacktestSnapshotPort,
        decision_port: BacktestDecisionPort,
        execution_port: BacktestExecutionPort | None = None,
        observed_events: list[str] | None = None,
    ) -> None:
        self._trading_days = trading_days
        self._warehouse = warehouse
        self._decision_port = decision_port
        self._execution_port = execution_port
        self.observed_events = observed_events if observed_events is not None else []

    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade = LlmGrade.NOT_USED,
    ) -> BacktestGroupResult:
        request = request.with_group(group)
        manifest = hashlib.sha256(
            json.dumps(request.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        ledger = PortfolioLedger.opening(request.initial_cash)
        days = self._trading_days.between(request.start_date, request.end_date)
        curve: list[dict[str, str]] = []
        trades: list[dict[str, str]] = []
        pending: tuple[BacktestDecision, ...] = ()
        equity_values: list[Decimal] = []
        states: Mapping[str, str] = {}
        for index, trading_day in enumerate(days):
            self.observed_events.append("pre_open_risk")
            self.observed_events.append("open_execution")
            for decision in pending:
                for intent in decision.intents:
                    self._execute_intent(intent, trading_day, ledger, trades)
            pending = ()
            self.observed_events.append("intraday_stops")
            self.observed_events.append("close_valuation")
            equity = ledger.state.cash + sum(
                (
                    position.average_cost * position.quantity
                    for position in ledger.state.positions.values()
                ),
                Decimal(0),
            )
            equity_values.append(equity)
            curve.append({"trade_date": trading_day.isoformat(), "equity": str(equity)})
            if index + 1 < len(days):
                self.observed_events.append("post_close_decision")
                as_of = datetime.combine(trading_day, time(15, 30), SHANGHAI)
                snapshot = self._warehouse.snapshot(
                    as_of_time=as_of,
                    scope=SnapshotScope.backtest(
                        (), datetime.combine(request.start_date, time.min, SHANGHAI)
                    ),
                )
                decision: BacktestDecision = self._decision_port.decide(
                    BacktestDecisionContext(
                        as_of,
                        days[index + 1],
                        request.strategy_version,
                        group,
                        snapshot,
                        ledger.to_portfolio_snapshot(as_of)
                        if hasattr(ledger, "to_portfolio_snapshot")
                        else _empty_portfolio(as_of, ledger.state.cash),
                        states,
                    )
                )
                states = decision.candidate_states
                pending = (decision,)
        return BacktestGroupResult(
            group=group,
            data_grade=DataGrade.RESEARCH,
            llm_grade=llm_grade,
            input_manifest_hash=manifest,
            equity_curve=curve,
            trades=trades,
            metrics=calculate_metrics(equity_values, request.initial_cash),
            warnings=["research_only"],
        )

    def _execute_intent(
        self,
        intent: OrderIntent,
        trade_date: date,
        ledger: PortfolioLedger,
        trades: list[dict[str, str]],
    ) -> None:
        if self._execution_port is None:
            return
        available = ledger.sellable_quantity(intent.security_id, trade_date)
        attempt = self._execution_port.execute(intent, trade_date, available)
        if isinstance(attempt, FilledAttempt):
            fill = ledger.apply_attempt(
                attempt, intent.security_id, intent.side, intent.strategy_book
            )
            trades.append(
                {
                    "order_id": fill.fill_id,
                    "signal_date": intent.signal_date.isoformat(),
                    "trade_date": fill.filled_at.date().isoformat(),
                    "security_id": fill.security_id,
                    "side": fill.side.value,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                }
            )


def _empty_portfolio(as_of: datetime, cash: Decimal) -> PortfolioSnapshot:

    return PortfolioSnapshot("backtest", as_of, 0, cash, cash, ())
