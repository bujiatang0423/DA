from datetime import date, datetime, timedelta
from decimal import Decimal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    PointInTimeSnapshot,
    SnapshotQuality,
    TemporalRecord,
)
from backend.app.features.backtests.engine import BacktestEngine, SHANGHAI
from backend.app.features.backtests.execution import FilledAttempt, RejectedAttempt
from backend.app.features.backtests.models import (
    BacktestRequest,
    OrderIntent,
    OrderSide,
    StrategyGroup,
)
from backend.app.features.backtests.ports import BacktestDecision, BacktestDecisionContext


def test_daily_event_order_and_next_day_execution_are_replayable() -> None:
    observed_events: list[str] = []
    requested_snapshots: list[datetime] = []

    class TradingDays:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            requested_snapshots.append(as_of_time)
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.RESEARCH,
                (),
                (),
                SnapshotQuality(()),
                (),
                "batch-1",
            )

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            if context.as_of_time.date() != date(2024, 1, 2):
                return BacktestDecision((), context.candidate_states)
            return BacktestDecision(
                (
                    OrderIntent(
                        order_id="order-1",
                        security_id="600000.SH",
                        side=OrderSide.BUY,
                        quantity=100,
                        signal_date=date(2024, 1, 2),
                        earliest_trade_date=date(2024, 1, 3),
                        strategy_book="core",
                        priority=100,
                        signal_close=Decimal("10"),
                    ),
                ),
                {"600000.SH": "watching"},
            )

    class Execution:
        def execute(
            self,
            intent: OrderIntent,
            trade_date: date,
            available_to_sell: int,
        ) -> FilledAttempt:
            return FilledAttempt(
                intent.order_id,
                trade_date,
                intent.quantity,
                Decimal("10"),
                Decimal("10"),
                Decimal("1"),
                Decimal("0"),
            )

    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 4),
        initial_cash=Decimal("10_000"),
        groups=[StrategyGroup.A],
        out_of_sample_start=date(2024, 1, 3),
    )
    engine = BacktestEngine(TradingDays(), Warehouse(), Decisions(), Execution(), observed_events)

    result = engine.run(request, StrategyGroup.A, LlmGrade.NOT_USED)
    replay = engine.run(request, StrategyGroup.A, LlmGrade.NOT_USED)

    assert observed_events[:5] == [
        "pre_open_risk",
        "open_execution",
        "intraday_stops",
        "close_valuation",
        "post_close_decision",
    ]
    assert result.equity_curve[0]["trade_date"] == "2024-01-02"
    assert result.trades[0]["signal_date"] == "2024-01-02"
    assert result.trades[0]["trade_date"] == "2024-01-03"
    assert result.trades[0]["theoretical_price"] == "10"
    assert result.trades[0]["slippage"] == "0"
    assert result.trades[0]["strategy_book"] == "core"
    assert result.metrics["annualized_return"] == "0"
    assert result.metric_details["acceptance_gates"][0]["reason"] == "INSUFFICIENT_CLOSED_TRADES"
    assert result.metric_details["values"]["market_regime"]["diagnostic"] == "MISSING_MARKET_REGIME"
    assert requested_snapshots[:2] == [
        datetime(2024, 1, 2, 15, 30, tzinfo=SHANGHAI),
        datetime(2024, 1, 3, 15, 30, tzinfo=SHANGHAI),
    ]
    assert result.model_dump(mode="json") == replay.model_dump(mode="json")


def test_manifest_changes_when_used_snapshot_batch_changes() -> None:
    class TradingDays:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 2), date(2024, 1, 3))

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            return BacktestDecision((), {})

    class Warehouse:
        def __init__(self, batch_id: str) -> None:
            self._batch_id = batch_id

        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.RESEARCH,
                (),
                (),
                SnapshotQuality(()),
                (LineageRef(self._batch_id, "fixture", "artifact"),),
                "unchanged-snapshot-manifest",
            )

    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        initial_cash=Decimal("10_000"),
        groups=[StrategyGroup.A],
    )

    first = BacktestEngine(TradingDays(), Warehouse("batch-1"), Decisions()).run(
        request, StrategyGroup.A
    )
    second = BacktestEngine(TradingDays(), Warehouse("batch-2"), Decisions()).run(
        request, StrategyGroup.A
    )

    assert first.input_manifest_hash != second.input_manifest_hash


def test_rejected_execution_attempt_is_auditable_without_becoming_a_trade() -> None:
    class TradingDays:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 2), date(2024, 1, 3))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.RESEARCH,
                (),
                (),
                SnapshotQuality(()),
                (),
                "batch-1",
            )

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            return BacktestDecision(
                (
                    OrderIntent(
                        order_id="rejected-order",
                        security_id="600000.SH",
                        side=OrderSide.BUY,
                        quantity=100,
                        signal_date=date(2024, 1, 2),
                        earliest_trade_date=date(2024, 1, 3),
                        strategy_book="core",
                        priority=100,
                        signal_close=Decimal("10"),
                    ),
                ),
                {},
            )

    class Execution:
        def execute(
            self,
            intent: OrderIntent,
            trade_date: date,
            available_to_sell: int,
        ) -> RejectedAttempt:
            return RejectedAttempt(
                intent.order_id,
                trade_date,
                0,
                "SUSPENDED",
                "pit:fee-2024",
            )

    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        initial_cash=Decimal("10_000"),
        groups=[StrategyGroup.A],
    )

    result = BacktestEngine(TradingDays(), Warehouse(), Decisions(), Execution()).run(
        request, StrategyGroup.A
    )

    assert result.trades == []
    assert result.rejected_attempts == [
        {
            "order_id": "rejected-order",
            "signal_date": "2024-01-02",
            "trade_date": "2024-01-03",
            "security_id": "600000.SH",
            "side": "buy",
            "requested_quantity": "100",
            "reason_code": "SUSPENDED",
            "fee_schedule_version": "pit:fee-2024",
        }
    ]


def test_engine_reports_realized_book_and_market_regime_performance() -> None:
    class TradingDays:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            regime = "bull" if as_of_time.date() == date(2024, 1, 2) else "bear"
            record = TemporalRecord(
                record_id=f"regime-{as_of_time.date().isoformat()}",
                kind=DataKind.INDEX_DAILY_BAR,
                entity_id="market",
                event_time=as_of_time,
                observed_at=as_of_time,
                available_at=as_of_time,
                source_artifact_hash="fixture-source",
                payload={"market_regime": regime},
            )
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.RESEARCH,
                (record,),
                (),
                SnapshotQuality(()),
                (),
                "market-regime-fixture",
            )

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            if context.as_of_time.date() == date(2024, 1, 2):
                return BacktestDecision((_order("buy-1", OrderSide.BUY, date(2024, 1, 3)),), {})
            if context.as_of_time.date() == date(2024, 1, 3):
                return BacktestDecision((_order("sell-1", OrderSide.SELL, date(2024, 1, 4)),), {})
            return BacktestDecision((), {})

    class Execution:
        def execute(
            self,
            intent: OrderIntent,
            trade_date: date,
            available_to_sell: int,
        ) -> FilledAttempt:
            del available_to_sell
            price = Decimal("10") if intent.side is OrderSide.BUY else Decimal("12")
            return FilledAttempt(
                intent.order_id,
                trade_date,
                100,
                price,
                price,
                Decimal("0"),
                Decimal("0"),
            )

    request = BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 4),
        initial_cash=Decimal("10000"),
        groups=[StrategyGroup.A],
        out_of_sample_start=date(2024, 1, 4),
    )

    result = BacktestEngine(TradingDays(), Warehouse(), Decisions(), Execution()).run(
        request, StrategyGroup.A
    )

    assert result.trades[-1]["realized_net_pnl"] == "200"
    assert result.metric_details["breakdowns"]["strategy_book"] == {"core": "200"}
    assert result.metric_details["breakdowns"]["market_regime"] == {
        "bear": "0.02",
        "bull": "0",
        "neutral": "0",
    }
    assert result.metric_details["acceptance_gates"][0]["observed"] == 1


def _order(order_id: str, side: OrderSide, earliest_trade_date: date) -> OrderIntent:
    return OrderIntent(
        order_id=order_id,
        security_id="600000.SH",
        side=side,
        quantity=100,
        signal_date=earliest_trade_date - timedelta(days=1),
        earliest_trade_date=earliest_trade_date,
        strategy_book="core",
        priority=100,
        signal_close=Decimal("10"),
    )
