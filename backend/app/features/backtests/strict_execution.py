from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from string import hexdigits
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.app.features.backtests.execution import DailyBar, FilledAttempt, RejectedAttempt
from backend.app.features.backtests.fees import FeeSchedule
from backend.app.features.backtests.models import OrderIntent
from backend.app.features.backtests.ports import BacktestExecutionPort
from backend.app.infrastructure.market.strict_queries import (
    FeeSchedule as HistoricalFeeSchedule,
    SecurityStatus,
    StrictDataMissingError,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRE_OPEN_TIME = time(9)
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


class SecurityQueries(Protocol):
    def status(self, security_id: str, as_of_time: datetime) -> SecurityStatus: ...


class ExecutionQueries(Protocol):
    def fee_schedule(
        self,
        *,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> HistoricalFeeSchedule: ...


class HistoricalDailyBarReader(Protocol):
    def bar_for(
        self,
        security_id: str,
        trade_date: date,
        *,
        as_of_time: datetime,
    ) -> DailyBar: ...


class StrictExecutionSimulator:
    def __init__(
        self,
        simulator: AttemptSimulator,
        securities: SecurityQueries,
        executions: ExecutionQueries,
    ) -> None:
        self._simulator = simulator
        self._securities = securities
        self._executions = executions

    def attempt(
        self,
        intent: OrderIntent,
        bar: DailyBar,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
        available_to_sell: int = 0,
    ) -> FilledAttempt | RejectedAttempt:
        status = self._securities.status(security_id, as_of_time)
        if bar.previous_close is None:
            raise StrictDataMissingError(f"previous close missing: {security_id}")
        dated = self._executions.fee_schedule(
            trade_date=trade_date,
            exchange=exchange,
            asset_type=asset_type,
            as_of_time=as_of_time,
        )
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
        bars: HistoricalDailyBarReader,
        timezone: ZoneInfo = SHANGHAI,
    ) -> None:
        self._simulator = simulator
        self._bars = bars
        self._timezone = timezone

    def execute(
        self, intent: OrderIntent, trade_date: date, available_to_sell: int
    ) -> FilledAttempt | RejectedAttempt:
        pre_open = datetime.combine(trade_date, PRE_OPEN_TIME, self._timezone)
        completed_bar = datetime.combine(trade_date, BAR_COMPLETION_TIME, self._timezone)
        return self._simulator.attempt(
            intent,
            self._bars.bar_for(
                intent.security_id,
                trade_date,
                as_of_time=completed_bar,
            ),
            security_id=intent.security_id,
            trade_date=trade_date,
            exchange=_exchange_for(intent.security_id),
            asset_type="stock",
            as_of_time=pre_open,
            available_to_sell=available_to_sell,
        )


def _exchange_for(security_id: str) -> str:
    if security_id.endswith(".SH"):
        return "SSE"
    if security_id.endswith(".SZ"):
        return "SZSE"
    raise StrictDataMissingError(f"exchange missing: {security_id}")
