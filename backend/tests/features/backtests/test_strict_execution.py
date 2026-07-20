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
from backend.app.features.backtests.strict_execution import (
    CertifiedExecutionInputs,
    StrictExecutionSimulator,
)
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.contracts.grades import DataGrade
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


class QueryExecutionInputs:
    def __init__(self, status: object, fees: object) -> None:
        self._status = status
        self._fees = fees

    def for_attempt(
        self,
        *,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> object:
        return type(
            "Inputs",
            (),
            {
                "bar": bar(),
                "status": self._status.status(security_id, as_of_time),
                "fee": self._fees.fee_schedule(
                    trade_date=trade_date,
                    exchange=exchange,
                    asset_type=asset_type,
                    as_of_time=as_of_time,
                ),
            },
        )()


def test_strict_attempt_injects_dated_fee_and_board_rule() -> None:
    recorder = RecordingSimulator()
    simulator = StrictExecutionSimulator(
        recorder, QueryExecutionInputs(PresentSecurityQueries(), PresentExecutionQueries())
    )

    result = simulator.attempt(
        order(),
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
        recorder, QueryExecutionInputs(PresentSecurityQueries(), MissingExecutionQueries())
    )

    with pytest.raises(StrictDataMissingError, match="fee schedule missing"):
        simulator.attempt(
            order(),
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
        recorder, QueryExecutionInputs(PresentSecurityQueries(), MissingHashExecutionQueries())
    )

    with pytest.raises(StrictDataMissingError, match="source artifact hash missing"):
        simulator.attempt(
            order(),
            security_id="PAST_DELISTED.SZ",
            trade_date=date(2020, 6, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=AS_OF,
        )

    assert recorder.calls == 0


def test_strict_attempt_uses_dated_fee_for_real_execution() -> None:
    simulator = StrictExecutionSimulator(
        ExecutionSimulator(),
        QueryExecutionInputs(PresentSecurityQueries(), PresentExecutionQueries()),
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
    result = simulator.attempt(
        intent,
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=AS_OF,
    )

    assert isinstance(result, FilledAttempt)
    assert result.fee == Decimal("5.01")
    assert result.fee_schedule_id == "fee-2020"


def test_certified_execution_inputs_use_one_attested_snapshot_for_bar_status_and_fee() -> None:
    snapshot = PointInTimeSnapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope(
            ("PAST_DELISTED.SZ",),
            (DataKind.DAILY_BAR_RAW, DataKind.SECURITY_STATUS, DataKind.FEE_SCHEDULE),
        ),
        data_grade=DataGrade.PIT_VERIFIED,
        market_inputs=(
            record(
                "fee-2020",
                DataKind.FEE_SCHEDULE,
                "SSE:stock",
                {
                    "exchange": "SSE",
                    "asset_type": "stock",
                    "effective_from": "2020-01-01",
                    "commission_rate": "0.0003",
                    "minimum_commission": "5",
                    "stamp_tax_sell_rate": "0.001",
                    "transfer_rate": "0.00001",
                },
            ),
        ),
        security_observations=(
            SecurityObservation(
                "PAST_DELISTED.SZ",
                (
                    record(
                        "status-2020",
                        DataKind.SECURITY_STATUS,
                        "PAST_DELISTED.SZ",
                        {
                            "trade_date": "2020-06-01",
                            "is_st": "False",
                            "is_suspended": "False",
                            "board": "main",
                            "price_limit_pct": "0.10",
                        },
                    ),
                    record(
                        "bar-prev",
                        DataKind.DAILY_BAR_RAW,
                        "PAST_DELISTED.SZ",
                        {
                            "trade_date": "2020-05-29",
                            "open": "9",
                            "high": "9",
                            "low": "9",
                            "close": "9",
                            "volume": "1000",
                        },
                    ),
                    record(
                        "bar-current",
                        DataKind.DAILY_BAR_RAW,
                        "PAST_DELISTED.SZ",
                        {
                            "trade_date": "2020-06-01",
                            "open": "10",
                            "high": "10",
                            "low": "10",
                            "close": "10",
                            "volume": "1000",
                        },
                    ),
                ),
            ),
        ),
        quality=SnapshotQuality(()),
        lineage=(),
        manifest_hash="manifest",
    )

    class CertifiedWarehouse:
        calls: list[tuple[datetime, object]] = []

        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            self.calls.append((as_of_time, scope))
            return snapshot

    warehouse = CertifiedWarehouse()
    inputs = CertifiedExecutionInputs(warehouse).for_attempt(
        security_id="PAST_DELISTED.SZ",
        trade_date=date(2020, 6, 1),
        exchange="SSE",
        asset_type="stock",
        as_of_time=AS_OF,
    )

    assert len(warehouse.calls) == 1
    assert inputs.bar.close == Decimal("10")
    assert inputs.status.is_st is False
    assert inputs.status.is_suspended is False
    assert inputs.status.price_limit_pct == Decimal("0.10")
    assert inputs.fee.record_id == "fee-2020"


def test_certified_execution_inputs_reject_future_visible_record_from_warehouse() -> None:
    future_record = record(
        "future-status",
        DataKind.SECURITY_STATUS,
        "PAST_DELISTED.SZ",
        {
            "trade_date": "2020-06-01",
            "is_st": False,
            "is_suspended": False,
            "board": "main",
            "price_limit_pct": "0.10",
        },
    )
    future_record = TemporalRecord(
        future_record.record_id,
        future_record.kind,
        future_record.entity_id,
        future_record.event_time,
        future_record.observed_at,
        AS_OF.replace(hour=10),
        future_record.source_artifact_hash,
        future_record.payload,
    )

    class FutureRecordWarehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.PIT_VERIFIED,
                (future_record,),
                (),
                SnapshotQuality(()),
                (),
                "manifest",
            )

    with pytest.raises(StrictDataMissingError, match="certified execution snapshot missing"):
        CertifiedExecutionInputs(FutureRecordWarehouse()).for_attempt(
            security_id="PAST_DELISTED.SZ",
            trade_date=date(2020, 6, 1),
            exchange="SSE",
            asset_type="stock",
            as_of_time=AS_OF,
        )


def record(
    record_id: str,
    kind: DataKind,
    entity_id: str,
    payload: dict[str, object],
) -> TemporalRecord:
    return TemporalRecord(record_id, kind, entity_id, AS_OF, AS_OF, AS_OF, "a" * 64, payload)


def order() -> OrderIntent:
    return OrderIntent(
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


def bar() -> DailyBar:
    return DailyBar(
        trade_date=date(2020, 6, 1),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=1_000,
        previous_close=Decimal("10"),
    )
