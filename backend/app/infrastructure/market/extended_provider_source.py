from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch


class ProviderDataUnavailableError(RuntimeError):
    """Raised when an extended provider cannot supply a requested PIT dataset."""


@dataclass(frozen=True)
class ProviderIndexBar:
    index_id: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    available_at: datetime
    source_artifact_hash: str


@dataclass(frozen=True)
class ProviderMarketBreadth:
    market_id: str
    event_time: datetime
    breadth: Decimal
    advancing_count: int
    declining_count: int
    security_count: int
    available_at: datetime
    source_artifact_hash: str


@dataclass(frozen=True)
class ProviderUniverseSecurity:
    security_id: str
    name: str
    listed_on: date
    valid_from: date
    valid_to: date | None
    available_at: datetime
    source_artifact_hash: str


@dataclass(frozen=True)
class ProviderMembership:
    security_id: str
    classification_id: str
    effective_from: date
    effective_to: date | None
    available_at: datetime
    source_artifact_hash: str


class ExtendedMarketDataProvider(Protocol):
    provider_name: str

    def index_daily_bars(
        self, index_id: str, start: date, end: date
    ) -> tuple[ProviderIndexBar, ...]: ...

    def market_breadth(self, as_of_time: datetime) -> ProviderMarketBreadth: ...

    def universe(self, as_of_time: datetime) -> tuple[ProviderUniverseSecurity, ...]: ...

    def industry_memberships(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ProviderMembership, ...]: ...

    def theme_memberships(
        self, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[ProviderMembership, ...]: ...


class ExtendedMarketProviderSource:
    """Translate externally supplied extended-market datasets into PIT records.

    This is deliberately not installed in the production composition root until a provider can
    supply every method with durable source artifacts. A missing or future-only required dataset
    causes the research warehouse to reject the snapshot instead of fabricating a data grade.
    """

    def __init__(
        self,
        provider: ExtendedMarketDataProvider,
        benchmark_ids: tuple[str, ...] = ("000985.CSI", "000001.SH"),
    ) -> None:
        self.provider = provider.provider_name
        self._provider = provider
        self._benchmark_ids = benchmark_ids

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        requested = set(scope.required_kinds)
        if not requested:
            requested = {
                DataKind.INDEX_DAILY_BAR,
                DataKind.MARKET_BREADTH,
                DataKind.SECURITY_MASTER,
                DataKind.INDUSTRY_MEMBERSHIP,
                DataKind.THEME_MEMBERSHIP,
            }
        records: list[TemporalRecord] = []
        needs_universe = DataKind.SECURITY_MASTER in requested or (
            not scope.security_ids and bool(requested & _MEMBERSHIP_KINDS)
        )
        universe = self._available_universe(as_of_time) if needs_universe else ()
        security_ids = scope.security_ids or tuple(row.security_id for row in universe)

        if DataKind.INDEX_DAILY_BAR in requested:
            records.extend(self._index_records(as_of_time, scope))
        if DataKind.MARKET_BREADTH in requested:
            records.append(self._breadth_record(as_of_time))
        if DataKind.SECURITY_MASTER in requested:
            universe_records = self._universe_records(universe, as_of_time)
            self._require_security_coverage(
                DataKind.SECURITY_MASTER, scope.security_ids, universe_records
            )
            records.extend(universe_records)
        if DataKind.INDUSTRY_MEMBERSHIP in requested:
            industry_records = self._membership_records(
                DataKind.INDUSTRY_MEMBERSHIP, security_ids, as_of_time
            )
            self._require_security_coverage(
                DataKind.INDUSTRY_MEMBERSHIP, security_ids, industry_records
            )
            records.extend(industry_records)
        if DataKind.THEME_MEMBERSHIP in requested:
            theme_records = self._membership_records(
                DataKind.THEME_MEMBERSHIP, security_ids, as_of_time
            )
            self._require_security_coverage(DataKind.THEME_MEMBERSHIP, security_ids, theme_records)
            records.extend(theme_records)

        present = {record.kind for record in records}
        missing = requested & _SUPPORTED_KINDS - present
        if missing:
            raise ProviderDataUnavailableError(
                "required extended dataset unavailable: "
                + ",".join(sorted(kind.value for kind in missing))
            )
        records_tuple = tuple(records)
        return ResearchBatch(records_tuple, _lineage(self.provider, records_tuple))

    def _available_universe(self, as_of_time: datetime) -> tuple[ProviderUniverseSecurity, ...]:
        return tuple(
            row for row in self._provider.universe(as_of_time) if row.available_at <= as_of_time
        )

    def _index_records(
        self, as_of_time: datetime, scope: SnapshotScope
    ) -> tuple[TemporalRecord, ...]:
        start = (scope.history_start or as_of_time - timedelta(days=400)).date()
        records = []
        for index_id in self._benchmark_ids:
            for row in self._provider.index_daily_bars(index_id, start, as_of_time.date()):
                if row.available_at > as_of_time:
                    continue
                event_time = datetime.combine(row.trade_date, time(15), as_of_time.tzinfo)
                records.append(
                    _record(
                        DataKind.INDEX_DAILY_BAR,
                        row.index_id,
                        row.trade_date.isoformat(),
                        event_time,
                        row.available_at,
                        row.source_artifact_hash,
                        asdict(row),
                    )
                )
        return tuple(records)

    def _breadth_record(self, as_of_time: datetime) -> TemporalRecord:
        row = self._provider.market_breadth(as_of_time)
        if row.available_at > as_of_time:
            raise ProviderDataUnavailableError("market_breadth is not available at as_of_time")
        return _record(
            DataKind.MARKET_BREADTH,
            row.market_id,
            row.event_time.isoformat(),
            row.event_time,
            row.available_at,
            row.source_artifact_hash,
            asdict(row),
        )

    @staticmethod
    def _universe_records(
        universe: tuple[ProviderUniverseSecurity, ...], as_of_time: datetime
    ) -> tuple[TemporalRecord, ...]:
        records = []
        for row in universe:
            if row.valid_from > as_of_time.date() or (
                row.valid_to is not None and row.valid_to <= as_of_time.date()
            ):
                continue
            records.append(
                _record(
                    DataKind.SECURITY_MASTER,
                    row.security_id,
                    row.valid_from.isoformat(),
                    datetime.combine(row.valid_from, time.min, as_of_time.tzinfo),
                    row.available_at,
                    row.source_artifact_hash,
                    asdict(row),
                )
            )
        return tuple(records)

    def _membership_records(
        self, kind: DataKind, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> tuple[TemporalRecord, ...]:
        if kind is DataKind.INDUSTRY_MEMBERSHIP:
            rows = self._provider.industry_memberships(security_ids, as_of_time)
        else:
            rows = self._provider.theme_memberships(security_ids, as_of_time)
        records = []
        for row in rows:
            if row.available_at > as_of_time:
                continue
            if row.effective_from > as_of_time.date() or (
                row.effective_to is not None and row.effective_to <= as_of_time.date()
            ):
                continue
            records.append(
                _record(
                    kind,
                    row.security_id,
                    f"{row.classification_id}:{row.effective_from.isoformat()}",
                    datetime.combine(row.effective_from, time.min, as_of_time.tzinfo),
                    row.available_at,
                    row.source_artifact_hash,
                    asdict(row),
                )
            )
        return tuple(records)

    @staticmethod
    def _require_security_coverage(
        kind: DataKind,
        security_ids: tuple[str, ...],
        records: tuple[TemporalRecord, ...],
    ) -> None:
        missing = set(security_ids) - {record.entity_id for record in records}
        if missing:
            raise ProviderDataUnavailableError(
                f"{kind.value} is unavailable for requested securities"
            )


_SUPPORTED_KINDS = frozenset(
    {
        DataKind.INDEX_DAILY_BAR,
        DataKind.MARKET_BREADTH,
        DataKind.SECURITY_MASTER,
        DataKind.INDUSTRY_MEMBERSHIP,
        DataKind.THEME_MEMBERSHIP,
    }
)

_MEMBERSHIP_KINDS = frozenset({DataKind.INDUSTRY_MEMBERSHIP, DataKind.THEME_MEMBERSHIP})


def _record(
    kind: DataKind,
    entity_id: str,
    suffix: str,
    event_time: datetime,
    available_at: datetime,
    source_artifact_hash: str,
    payload: dict[str, object],
) -> TemporalRecord:
    return TemporalRecord(
        record_id=f"{kind.value}:{entity_id}:{suffix}",
        kind=kind,
        entity_id=entity_id,
        event_time=event_time,
        observed_at=available_at,
        available_at=available_at,
        source_artifact_hash=source_artifact_hash,
        payload=payload,
    )


def _lineage(provider: str, records: tuple[TemporalRecord, ...]) -> tuple[LineageRef, ...]:
    return tuple(
        LineageRef(f"{provider}-{source_hash[:16]}", provider, source_hash)
        for source_hash in sorted({record.source_artifact_hash for record in records})
    )
