from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from string import hexdigits
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade
from backend.app.features.backtests.execution import DailyBar, FilledAttempt, RejectedAttempt
from backend.app.features.backtests.fees import FeeSchedule
from backend.app.features.backtests.models import OrderIntent
from backend.app.core.market.pit_models import (
    DataKind,
    PointInTimeSnapshot,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.features.backtests.ports import BacktestExecutionPort, BacktestSnapshotPort
from backend.app.infrastructure.market.strict_queries import (
    FeeSchedule as HistoricalFeeSchedule,
    SecurityStatus,
    StrictDataMissingError,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
BAR_COMPLETION_TIME = time(15)


class AttemptSimulator(Protocol):
    def attempt(
        self,
        intent: OrderIntent,
        bar: DailyBar,
        *,
        fee_schedule: FeeSchedule,
        price_limit_pct: Decimal,
        available_to_sell: int = 0,
    ) -> FilledAttempt | RejectedAttempt: ...


@dataclass(frozen=True)
class CertifiedExecutionInput:
    bar: DailyBar
    status: SecurityStatus
    fee: HistoricalFeeSchedule


class ExecutionInputReader(Protocol):
    def for_attempt(
        self,
        *,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> CertifiedExecutionInput: ...


class HistoricalDailyBarReader(Protocol):
    def bar_for(
        self,
        security_id: str,
        trade_date: date,
        *,
        as_of_time: datetime,
    ) -> DailyBar: ...


class CertifiedExecutionInputs:
    """Decode all fill inputs from one approved strict PIT snapshot."""

    def __init__(self, warehouse: BacktestSnapshotPort) -> None:
        self._warehouse = warehouse

    def for_attempt(
        self,
        *,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> CertifiedExecutionInput:
        scope = SnapshotScope(
            (security_id,),
            (DataKind.DAILY_BAR_RAW, DataKind.SECURITY_STATUS, DataKind.FEE_SCHEDULE),
        )
        snapshot = self._warehouse.snapshot(as_of_time=as_of_time, scope=scope)
        _validate_snapshot(snapshot, as_of_time, scope)
        records = tuple(_snapshot_records(snapshot))
        return CertifiedExecutionInput(
            _daily_bar(records, security_id, trade_date),
            _security_status(records, security_id, trade_date),
            _fee_schedule(records, trade_date, exchange, asset_type),
        )


class StrictExecutionSimulator:
    def __init__(
        self,
        simulator: AttemptSimulator,
        inputs: ExecutionInputReader,
    ) -> None:
        self._simulator = simulator
        self._inputs = inputs

    def attempt(
        self,
        intent: OrderIntent,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
        available_to_sell: int = 0,
    ) -> FilledAttempt | RejectedAttempt:
        inputs = self._inputs.for_attempt(
            security_id=security_id,
            trade_date=trade_date,
            exchange=exchange,
            asset_type=asset_type,
            as_of_time=as_of_time,
        )
        bar = inputs.bar
        status = inputs.status
        if bar.previous_close is None:
            raise StrictDataMissingError(f"previous close missing: {security_id}")
        dated = inputs.fee
        self._validate_artifact_hash(dated.source_artifact_hash)
        fee_schedule = FeeSchedule(
            version=f"pit:{dated.record_id}:{dated.source_artifact_hash}",
            commission_rate=dated.commission_rate,
            minimum_commission=dated.minimum_commission,
            stamp_tax_sell_rate=dated.stamp_tax_sell_rate,
            transfer_rate=dated.transfer_rate,
        )
        result = self._simulator.attempt(
            intent,
            replace(bar, suspended=bar.suspended or status.is_suspended),
            fee_schedule=fee_schedule,
            price_limit_pct=status.price_limit_pct,
            available_to_sell=available_to_sell,
        )
        return replace(
            result,
            fee_schedule_id=dated.record_id,
            fee_schedule_hash=dated.source_artifact_hash,
        )

    @staticmethod
    def _validate_artifact_hash(source_artifact_hash: str) -> None:
        if len(source_artifact_hash) != 64 or any(
            char not in hexdigits for char in source_artifact_hash
        ):
            raise StrictDataMissingError("fee schedule source artifact hash missing")


class StrictBacktestExecutionPort(BacktestExecutionPort):
    """Use pre-open metadata and a completed daily bar for intraday simulation."""

    def __init__(
        self,
        simulator: StrictExecutionSimulator,
        timezone: ZoneInfo = SHANGHAI,
    ) -> None:
        self._simulator = simulator
        self._timezone = timezone

    def execute(
        self, intent: OrderIntent, trade_date: date, available_to_sell: int
    ) -> FilledAttempt | RejectedAttempt:
        completed_bar = datetime.combine(trade_date, BAR_COMPLETION_TIME, self._timezone)
        return self._simulator.attempt(
            intent,
            security_id=intent.security_id,
            trade_date=trade_date,
            exchange=_exchange_for(intent.security_id),
            asset_type="stock",
            as_of_time=completed_bar,
            available_to_sell=available_to_sell,
        )


def _exchange_for(security_id: str) -> str:
    if security_id.endswith(".SH"):
        return "SSE"
    if security_id.endswith(".SZ"):
        return "SZSE"
    raise StrictDataMissingError(f"exchange missing: {security_id}")


def _validate_snapshot(
    snapshot: PointInTimeSnapshot,
    as_of_time: datetime,
    scope: SnapshotScope,
) -> None:
    if (
        snapshot.data_grade is not DataGrade.PIT_VERIFIED
        or snapshot.as_of_time != as_of_time
        or snapshot.scope != scope
        or snapshot.quality.has_errors
    ):
        raise StrictDataMissingError("certified execution snapshot missing")


def _snapshot_records(snapshot: PointInTimeSnapshot) -> tuple[TemporalRecord, ...]:
    return snapshot.market_inputs + tuple(
        record for observation in snapshot.security_observations for record in observation.records
    )


def _daily_bar(records: tuple[TemporalRecord, ...], security_id: str, trade_date: date) -> DailyBar:
    matching = [
        record
        for record in records
        if record.kind is DataKind.DAILY_BAR_RAW
        and record.entity_id == security_id
        and _date(record, "trade_date") == trade_date
    ]
    current = max(matching, key=lambda item: item.record_id, default=None)
    if current is None:
        raise StrictDataMissingError(f"certified daily bar missing: {security_id}")
    previous = max(
        (
            record
            for record in records
            if record.kind is DataKind.DAILY_BAR_RAW
            and record.entity_id == security_id
            and _date(record, "trade_date") < trade_date
        ),
        key=lambda item: (_date(item, "trade_date"), item.record_id),
        default=None,
    )
    if previous is None:
        raise StrictDataMissingError(f"certified previous close missing: {security_id}")
    return DailyBar(
        trade_date=trade_date,
        open=_decimal(current, "open"),
        high=_decimal(current, "high"),
        low=_decimal(current, "low"),
        close=_decimal(current, "close"),
        volume=int(str(current.payload["volume"])),
        previous_close=_decimal(previous, "close"),
    )


def _security_status(
    records: tuple[TemporalRecord, ...], security_id: str, trade_date: date
) -> SecurityStatus:
    record = next(
        (
            item
            for item in records
            if item.kind is DataKind.SECURITY_STATUS
            and item.entity_id == security_id
            and _date(item, "trade_date") == trade_date
        ),
        None,
    )
    if record is None:
        raise StrictDataMissingError(f"certified security status missing: {security_id}")
    return SecurityStatus(
        bool(record.payload["is_st"]),
        bool(record.payload["is_suspended"]),
        str(record.payload["board"]),
        _decimal(record, "price_limit_pct"),
    )


def _fee_schedule(
    records: tuple[TemporalRecord, ...], trade_date: date, exchange: str, asset_type: str
) -> HistoricalFeeSchedule:
    candidates = [
        record
        for record in records
        if record.kind is DataKind.FEE_SCHEDULE
        and str(record.payload.get("exchange")) == exchange
        and str(record.payload.get("asset_type")) == asset_type
        and _date(record, "effective_from") <= trade_date
        and (
            record.payload.get("effective_to") in (None, "")
            or _date(record, "effective_to") > trade_date
        )
    ]
    record = max(
        candidates, key=lambda item: (_date(item, "effective_from"), item.record_id), default=None
    )
    if record is None:
        raise StrictDataMissingError("certified fee schedule missing")
    return HistoricalFeeSchedule(
        record.record_id,
        record.source_artifact_hash,
        _decimal(record, "commission_rate"),
        _decimal(record, "minimum_commission"),
        _decimal(record, "stamp_tax_sell_rate"),
        _decimal(record, "transfer_rate"),
    )


def _date(record: TemporalRecord, field: str) -> date:
    return date.fromisoformat(str(record.payload[field]))


def _decimal(record: TemporalRecord, field: str) -> Decimal:
    return Decimal(str(record.payload[field]))
