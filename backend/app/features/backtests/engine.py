from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests.ledger import PortfolioLedger
from backend.app.features.backtests.execution import FilledAttempt, RejectedAttempt
from backend.app.features.backtests.metrics import calculate_metrics
from backend.app.features.backtests.models import (
    BacktestGroupResult,
    BacktestRequest,
    OrderIntent,
    StrategyGroup,
)
from backend.app.features.backtests.ports import (
    ALL_STRATEGY_FACTORS,
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
        data_grade: DataGrade = DataGrade.RESEARCH,
    ) -> None:
        self._trading_days = trading_days
        self._warehouse = warehouse
        self._decision_port = decision_port
        self._execution_port = execution_port
        self._data_grade = data_grade
        self.observed_events = observed_events if observed_events is not None else []

    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade = LlmGrade.NOT_USED,
        *,
        factor_mask: frozenset[str] = ALL_STRATEGY_FACTORS,
    ) -> BacktestGroupResult:
        request = request.with_group(group)
        ledger = PortfolioLedger.opening(request.initial_cash)
        days = self._trading_days.between(request.start_date, request.end_date)
        curve: list[dict[str, str]] = []
        trades: list[dict[str, str]] = []
        rejected_attempts: list[dict[str, str]] = []
        snapshots: list[PointInTimeSnapshot] = []
        pending: tuple[BacktestDecision, ...] = ()
        equity_values: list[Decimal] = []
        states: Mapping[str, str] = {}
        for index, trading_day in enumerate(days):
            self.observed_events.append("pre_open_risk")
            self.observed_events.append("open_execution")
            for decision in pending:
                for intent in decision.intents:
                    self._execute_intent(intent, trading_day, ledger, trades, rejected_attempts)
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
                snapshots.append(snapshot)
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
                        factor_mask,
                    )
                )
                states = decision.candidate_states
                pending = (decision,)
        return BacktestGroupResult(
            group=group,
            data_grade=self._data_grade,
            llm_grade=llm_grade,
            input_manifest_hash=self._manifest_hash(request, snapshots),
            equity_curve=curve,
            trades=trades,
            rejected_attempts=rejected_attempts,
            metrics=calculate_metrics(equity_values, request.initial_cash),
            comparison_inputs=self._comparison_inputs(request, snapshots),
            warnings=["research_only"] if self._data_grade is DataGrade.RESEARCH else [],
        )

    def _execute_intent(
        self,
        intent: OrderIntent,
        trade_date: date,
        ledger: PortfolioLedger,
        trades: list[dict[str, str]],
        rejected_attempts: list[dict[str, str]],
    ) -> None:
        if self._execution_port is None:
            return
        available = ledger.sellable_quantity(intent.security_id, trade_date)
        attempt = self._execution_port.execute(intent, trade_date, available)
        if isinstance(attempt, FilledAttempt):
            fill = ledger.apply_attempt(
                attempt, intent.security_id, intent.side, intent.strategy_book
            )
            trade = {
                "order_id": fill.fill_id,
                "signal_date": intent.signal_date.isoformat(),
                "trade_date": fill.filled_at.date().isoformat(),
                "security_id": fill.security_id,
                "side": fill.side.value,
                "quantity": str(fill.quantity),
                "price": str(fill.price),
                "fee": str(fill.fee),
            }
            if attempt.fee_schedule_id is not None:
                trade["fee_schedule_id"] = attempt.fee_schedule_id
            if attempt.fee_schedule_hash is not None:
                trade["fee_schedule_hash"] = attempt.fee_schedule_hash
            trades.append(trade)
        elif isinstance(attempt, RejectedAttempt):
            rejected = {
                "order_id": attempt.order_id,
                "signal_date": intent.signal_date.isoformat(),
                "trade_date": attempt.trade_date.isoformat(),
                "security_id": intent.security_id,
                "side": intent.side.value,
                "requested_quantity": str(intent.quantity),
                "reason_code": attempt.reason_code,
                "fee_schedule_version": attempt.fee_schedule_version,
            }
            if attempt.fee_schedule_id is not None:
                rejected["fee_schedule_id"] = attempt.fee_schedule_id
            if attempt.fee_schedule_hash is not None:
                rejected["fee_schedule_hash"] = attempt.fee_schedule_hash
            rejected_attempts.append(rejected)

    @staticmethod
    def _manifest_hash(
        request: BacktestRequest,
        snapshots: list[PointInTimeSnapshot],
    ) -> str:
        payload = {
            "request": request.model_dump(mode="json"),
            "snapshots": [
                {
                    "as_of_time": snapshot.as_of_time.isoformat(),
                    "batch_ids": sorted(lineage.batch_id for lineage in snapshot.lineage),
                    "snapshot_manifest_hash": snapshot.manifest_hash,
                }
                for snapshot in snapshots
            ],
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _comparison_inputs(
        request: BacktestRequest,
        snapshots: list[PointInTimeSnapshot],
    ) -> dict[str, str]:
        snapshot_payload = [
            {
                "as_of_time": snapshot.as_of_time.isoformat(),
                "batch_ids": sorted(lineage.batch_id for lineage in snapshot.lineage),
                "snapshot_manifest_hash": snapshot.manifest_hash,
            }
            for snapshot in snapshots
        ]
        universe_payload = [sorted(snapshot.scope.security_ids) for snapshot in snapshots]
        market_filter_payload = [
            sorted(kind.value for kind in snapshot.scope.required_kinds) for snapshot in snapshots
        ]
        execution_payload = {
            "buy_slippage_bps": request.buy_slippage_bps,
            "sell_slippage_bps": request.sell_slippage_bps,
            "fee_schedule_version": request.fee_schedule_version,
        }
        return {
            "pit_input_manifest_hash": _hash_payload(snapshot_payload),
            "universe_hash": _hash_payload(universe_payload),
            "market_filter_hash": _hash_payload(market_filter_payload),
            "execution_settings_hash": _hash_payload(execution_payload),
            "fee_schedule_version": request.fee_schedule_version,
            "risk_budget": "not_configured",
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        }


def _empty_portfolio(as_of: datetime, cash: Decimal) -> PortfolioSnapshot:

    return PortfolioSnapshot("backtest", as_of, 0, cash, cash, ())


def _hash_payload(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()
