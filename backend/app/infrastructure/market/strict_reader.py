from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date, datetime, time
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.infrastructure.persistence.strict_pit_rows import (
    AdjustmentFactorRow,
    CorporateActionRow,
    DailyBarRawRow,
    FeeScheduleRow,
    FinancialDisclosureRow,
    FinancialFactRow,
    IndexDailyBarRow,
    IndustryMembershipHistoryRow,
    MarketBreadthRow,
    PolicyDocumentRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
    ThemeMembershipHistoryRow,
    TradingCalendarRow,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class StrictRow(Protocol):
    id: str
    source_record_id: str
    available_at: datetime
    source_artifact_hash: str
    security_id: Any
    index_id: Any
    market_id: Any
    universe_id: Any
    trade_date: Any
    exchange: Any
    asset_type: Any
    report_period: Any
    disclosure_id: Any
    metric: Any
    valid_from: Any
    valid_to: Any
    payload_json: Any
    effective_from: Any
    effective_to: Any
    published_at: Any
    __table__: Any


ROW_MODELS: dict[DataKind, type[object]] = {
    DataKind.SECURITY_MASTER: SecurityMasterHistoryRow,
    DataKind.SECURITY_STATUS: SecurityStatusDailyRow,
    DataKind.TRADING_CALENDAR: TradingCalendarRow,
    DataKind.DAILY_BAR_RAW: DailyBarRawRow,
    DataKind.INDEX_DAILY_BAR: IndexDailyBarRow,
    DataKind.MARKET_BREADTH: MarketBreadthRow,
    DataKind.CORPORATE_ACTION: CorporateActionRow,
    DataKind.ADJUSTMENT_FACTOR: AdjustmentFactorRow,
    DataKind.INDUSTRY_MEMBERSHIP: IndustryMembershipHistoryRow,
    DataKind.THEME_MEMBERSHIP: ThemeMembershipHistoryRow,
    DataKind.FINANCIAL_DISCLOSURE: FinancialDisclosureRow,
    DataKind.POLICY_DOCUMENT: PolicyDocumentRow,
    DataKind.FEE_SCHEDULE: FeeScheduleRow,
}


class SqlStrictRecordReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def read(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> tuple[tuple[TemporalRecord, ...], tuple[LineageRef, ...], tuple[QualityIssue, ...]]:
        requested = scope.required_kinds or tuple(ROW_MODELS) + (DataKind.FINANCIAL_FACT,)
        if DataKind.FINANCIAL_FACT in requested and DataKind.FINANCIAL_DISCLOSURE not in requested:
            requested = (*requested, DataKind.FINANCIAL_DISCLOSURE)
        requested = tuple(
            kind for kind in requested if kind is not DataKind.FINANCIAL_FACT
        ) + tuple(kind for kind in requested if kind is DataKind.FINANCIAL_FACT)
        records: list[TemporalRecord] = []
        issues: list[QualityIssue] = []
        selected_disclosures: set[str] = set()
        disclosure_security_ids: dict[str, str] = {}

        for kind in requested:
            if kind is DataKind.FINANCIAL_FACT:
                rows = self._financial_facts(as_of_time, selected_disclosures)
            else:
                model = ROW_MODELS.get(kind)
                if model is None:
                    issues.append(_missing_issue(kind))
                    continue
                rows = self._rows(model, as_of_time, scope)
                rows = self._select_effective(kind, rows, as_of_time)
                if kind is DataKind.FINANCIAL_DISCLOSURE:
                    selected_disclosures = {str(row.id) for row in rows}
                    disclosure_security_ids = {str(row.id): str(row.security_id) for row in rows}
            if not rows:
                issues.append(_missing_issue(kind))
                continue
            records.extend(_to_record(kind, row, disclosure_security_ids) for row in rows)

        ordered = tuple(sorted(records, key=lambda item: (item.kind.value, item.record_id)))
        hashes = sorted({record.source_artifact_hash for record in ordered})
        lineage = tuple(
            LineageRef(f"strict-{digest[:16]}", "strict_pit_bundle", digest) for digest in hashes
        )
        return ordered, lineage, tuple(issues)

    def _rows(
        self,
        model: type[object],
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> list[StrictRow]:
        statement = select(model).where(model.available_at <= as_of_time)
        if hasattr(model, "trade_date"):
            statement = statement.where(model.trade_date <= as_of_time.date())
        if scope.security_ids and hasattr(model, "security_id"):
            statement = statement.where(model.security_id.in_(scope.security_ids))
        if model is MarketBreadthRow:
            statement = statement.where(
                MarketBreadthRow.market_id == scope.market_id,
                MarketBreadthRow.universe_id == scope.universe_id,
            )
        return cast(list[StrictRow], list(self._session.scalars(statement)))

    def _financial_facts(
        self,
        as_of_time: datetime,
        disclosure_ids: set[str],
    ) -> list[StrictRow]:
        if not disclosure_ids:
            return []
        rows = self._session.scalars(
            select(FinancialFactRow).where(
                FinancialFactRow.available_at <= as_of_time,
                FinancialFactRow.disclosure_id.in_(disclosure_ids),
            )
        ).all()
        return _latest_by(
            cast(list[StrictRow], rows),
            lambda row: (row.disclosure_id, row.metric),
        )

    @staticmethod
    def _select_effective(
        kind: DataKind,
        rows: Iterable[StrictRow],
        as_of_time: datetime,
    ) -> list[StrictRow]:
        eligible = [row for row in rows if _effective_at(kind, row, as_of_time)]
        return _latest_by(eligible, lambda row: _version_key(kind, row))


def _missing_issue(kind: DataKind) -> QualityIssue:
    return QualityIssue(
        "REQUIRED_DATASET_MISSING",
        QualitySeverity.ERROR,
        kind.value,
        None,
        "strict point-in-time dataset is unavailable",
    )


def _latest_by(
    rows: Iterable[StrictRow],
    key: Callable[[StrictRow], object],
) -> list[StrictRow]:
    selected: dict[object, StrictRow] = {}
    for row in rows:
        row_key = key(row)
        current = selected.get(row_key)
        if current is None or (row.available_at, row.id) > (current.available_at, current.id):
            selected[row_key] = row
    return list(selected.values())


def _effective_at(kind: DataKind, row: StrictRow, as_of_time: datetime) -> bool:
    as_of_date = as_of_time.date()
    if kind is DataKind.SECURITY_MASTER:
        valid_from = cast(date, row.valid_from)
        valid_to = cast(date | None, row.valid_to)
        return valid_from <= as_of_date and (valid_to is None or valid_to > as_of_date)
    if kind in {DataKind.INDUSTRY_MEMBERSHIP, DataKind.THEME_MEMBERSHIP}:
        payload = json.loads(cast(str, row.payload_json))
        start = date.fromisoformat(payload["effective_from"])
        end_value = payload.get("effective_to") or None
        end = date.fromisoformat(end_value) if end_value else None
        return start <= as_of_date and (end is None or end > as_of_date)
    if kind is DataKind.CORPORATE_ACTION:
        payload = json.loads(cast(str, row.payload_json))
        ex_date = date.fromisoformat(str(payload["ex_date"]))
        return ex_date <= as_of_date
    if kind is DataKind.ADJUSTMENT_FACTOR:
        payload = json.loads(cast(str, row.payload_json))
        trade_date = date.fromisoformat(str(payload["trade_date"]))
        return trade_date <= as_of_date
    if kind is DataKind.FEE_SCHEDULE:
        effective_from = cast(date, row.effective_from)
        effective_to = cast(date | None, row.effective_to)
        return effective_from <= as_of_date and (effective_to is None or effective_to > as_of_date)
    if kind is DataKind.MARKET_BREADTH:
        return cast(date, row.trade_date) == as_of_date
    return True


def _version_key(kind: DataKind, row: StrictRow) -> object:
    if kind is DataKind.SECURITY_MASTER:
        return row.security_id
    if kind is DataKind.SECURITY_STATUS:
        return row.security_id, row.trade_date
    if kind is DataKind.TRADING_CALENDAR:
        return row.exchange, row.trade_date
    if kind is DataKind.DAILY_BAR_RAW:
        return row.security_id, row.trade_date
    if kind is DataKind.INDEX_DAILY_BAR:
        return row.index_id, row.trade_date
    if kind is DataKind.MARKET_BREADTH:
        return row.market_id, row.universe_id, row.trade_date
    if kind is DataKind.FINANCIAL_DISCLOSURE:
        return row.security_id, row.report_period
    if kind is DataKind.FEE_SCHEDULE:
        return row.exchange, row.asset_type
    return row.source_record_id


def _to_record(
    kind: DataKind,
    row: StrictRow,
    disclosure_security_ids: dict[str, str],
) -> TemporalRecord:
    if hasattr(row, "payload_json"):
        payload = json.loads(row.payload_json)
    else:
        payload = {
            column.name: _payload_value(getattr(row, column.name))
            for column in row.__table__.columns
            if column.name not in {"id", "available_at", "source_artifact_hash"}
        }
    event_date = getattr(row, "trade_date", None)
    event_time = (
        datetime.combine(event_date, time(15), SHANGHAI)
        if event_date is not None
        else getattr(row, "published_at", row.available_at)
    )
    entity_id = getattr(row, "security_id", None)
    if kind is DataKind.FINANCIAL_FACT:
        entity_id = disclosure_security_ids.get(str(row.disclosure_id))
    if kind is DataKind.INDEX_DAILY_BAR:
        entity_id = f"MARKET:{row.index_id}"
    if kind is DataKind.MARKET_BREADTH:
        entity_id = f"MARKET:{row.market_id}"
    if entity_id is None:
        entity_id = getattr(row, "index_id", f"MARKET:{kind.value}")
    return TemporalRecord(
        str(row.id),
        kind,
        str(entity_id),
        event_time,
        row.available_at,
        row.available_at,
        row.source_artifact_hash,
        payload,
    )


def _payload_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
