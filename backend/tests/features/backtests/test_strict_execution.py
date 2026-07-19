from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from backend.app.features.backtests.execution import (
    DailyBar,
    ExecutionSimulator,
    FilledAttempt,
    RejectedAttempt,
)
from backend.app.features.backtests.fees import FeeSchedule
from backend.app.features.backtests.models import OrderIntent, OrderSide
from backend.app.features.backtests.strict_execution import StrictExecutionSimulator
from backend.app.infrastructure.market.strict_queries import (
    FeeSchedule as HistoricalFeeSchedule,
    SecurityStatus,
    StrictDataMissingError,
)


AS_OF = datetime(2020, 6, 1, 9, 0, tzinfo=UTC)


@dataclass
class RecordingSimulator:
    calls: int = 0
    fee_schedule: FeeSchedule | None = None
    price_limit_pct: Decimal | None = None

    def attempt(
        self,
        *args: object,
        fee_schedule: FeeSchedule,
        price_limit_pct: Decimal,
        **kwargs: object,
    ) -> FilledAttempt | RejectedAttempt:
        self.calls += 1
        self.fee_schedule = fee_schedule
        self.price_limit_pct = price_limit_pct
        return FilledAttempt(
            order_id="order-1",
            trade_date=date(2020, 6, 1),
            quantity=100,
            theoretical_price=Decimal("10"),
            actual_price=Decimal("10"),
            fee=Decimal("5"),
            slippage=Decimal("0"),
        )


class PresentSecurityQueries:
    def status(self, security_id: str, as_of_time: datetime) -> SecurityStatus:
        assert security_id == "PAST_DELISTED.SZ"
        assert as_of_time == AS_OF
        return SecurityStatus(False, False, "main", Decimal("0.10"))


class PresentExecutionQueries:
    def fee_schedule(
        self,
        *,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> HistoricalFeeSchedule:
        assert (trade_date, exchange, asset_type, as_of_time) == (
            date(2020, 6, 1),
            "SSE",
            "stock",
            AS_OF,
        )
        return HistoricalFeeSchedule(
            "fee-2020",
            "a" * 64,
            Decimal("0.0003"),
            Decimal("5"),
            Decimal("0.001"),
            Decimal("0.00001"),
        )


class MissingExecutionQueries:
    def fee_schedule(self, **kwargs: object) -> HistoricalFeeSchedule:
        raise StrictDataMissingError("fee schedule missing")


class MissingHashExecutionQueries(PresentExecutionQueries):
    def fee_schedule(
        self,
        *,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> HistoricalFeeSchedule:
        schedule = super().fee_schedule(
            trade_date=trade_date,
            exchange=exchange,
            asset_type=asset_type,
            as_of_time=as_of_time,
        )
        return HistoricalFeeSchedule(
            schedule.record_id,
            "",
            schedule.commission_rate,
            schedule.minimum_commission,
            schedule.stamp_tax_sell_rate,
            schedule.transfer_rate,
        )


def test_strict_attempt_injects_dated_fee_and_board_rule() -> None:
    recorder = RecordingSimulator()
    simulator = StrictExecutionSimulator(
        recorder, PresentSecurityQueries(), PresentExecutionQueries()
    )

    result = simulator.attempt(
        object(),
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=AS_OF,
    )

    assert recorder.price_limit_pct == Decimal("0.10")
    assert recorder.fee_schedule is not None
    assert recorder.fee_schedule.version == f"pit:fee-2020:{'a' * 64}"
    assert result.fee_schedule_id == "fee-2020"
    assert result.fee_schedule_hash == "a" * 64


def test_strict_attempt_fails_before_execution_without_dated_fee() -> None:
    recorder = RecordingSimulator()
    simulator = StrictExecutionSimulator(
        recorder, PresentSecurityQueries(), MissingExecutionQueries()
    )

    with pytest.raises(StrictDataMissingError, match="fee schedule missing"):
        simulator.attempt(
            object(),
            security_id="PAST_DELISTED.SZ",
            trade_date=date(2020, 6, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=AS_OF,
        )

    assert recorder.calls == 0


def test_strict_attempt_fails_before_execution_without_fee_artifact_hash() -> None:
    recorder = RecordingSimulator()
    simulator = StrictExecutionSimulator(
        recorder, PresentSecurityQueries(), MissingHashExecutionQueries()
    )

    with pytest.raises(StrictDataMissingError, match="source artifact hash missing"):
        simulator.attempt(
            object(),
            security_id="PAST_DELISTED.SZ",
            trade_date=date(2020, 6, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=AS_OF,
        )

    assert recorder.calls == 0


def test_strict_attempt_uses_dated_fee_for_real_execution() -> None:
    simulator = StrictExecutionSimulator(
        ExecutionSimulator(), PresentSecurityQueries(), PresentExecutionQueries()
    )
    intent = OrderIntent(
        order_id="order-1",
        security_id="PAST_DELISTED.SZ",
        side=OrderSide.BUY,
        quantity=100,
        signal_date=date(2020, 5, 29),
        earliest_trade_date=date(2020, 6, 1),
        strategy_book="core",
        priority=100,
        signal_close=Decimal("10"),
        max_participation_rate=Decimal("1"),
    )
    bar = DailyBar(
        trade_date=date(2020, 6, 1),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=1_000,
    )

    result = simulator.attempt(
        intent,
        bar,
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=AS_OF,
    )

    assert isinstance(result, FilledAttempt)
    assert result.fee == Decimal("5.01")
    assert result.fee_schedule_id == "fee-2020"
