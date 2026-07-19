from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from string import hexdigits
from typing import Protocol

from backend.app.features.backtests.execution import FilledAttempt, RejectedAttempt
from backend.app.features.backtests.fees import FeeSchedule
from backend.app.infrastructure.market.strict_queries import (
    FeeSchedule as HistoricalFeeSchedule,
    SecurityStatus,
    StrictDataMissingError,
)


class AttemptSimulator(Protocol):
    def attempt(
        self,
        *args: object,
        fee_schedule: FeeSchedule,
        price_limit_pct: object,
        **kwargs: object,
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
        *args: object,
        security_id: str,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
        **kwargs: object,
    ) -> FilledAttempt | RejectedAttempt:
        status = self._securities.status(security_id, as_of_time)
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
            *args,
            fee_schedule=fee_schedule,
            price_limit_pct=status.price_limit_pct,
            **kwargs,
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
