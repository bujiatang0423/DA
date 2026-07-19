from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.persistence.strict_pit_rows import (
    FinancialDisclosureRow,
    FinancialFactRow,
    FeeScheduleRow,
    IndustryMembershipHistoryRow,
    PolicyDocumentRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
)


class StrictDataMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityStatus:
    is_st: bool
    is_suspended: bool
    board: str
    price_limit_pct: Decimal


@dataclass(frozen=True)
class FeeSchedule:
    record_id: str
    source_artifact_hash: str
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_sell_rate: Decimal
    transfer_rate: Decimal


@dataclass(frozen=True)
class FinancialDisclosure:
    disclosure_id: str
    revision: int
    published_at: datetime
    available_at: datetime
    facts: dict[str, str]


@dataclass(frozen=True)
class PolicyDocument:
    document_id: str
    available_at: datetime
    evidence_grade: str
    scoreable: bool


class TemporalSecurityQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def universe(self, as_of_time: datetime) -> tuple[str, ...]:
        as_of_date = as_of_time.date()
        rows = self._session.scalars(
            select(SecurityMasterHistoryRow).where(
                SecurityMasterHistoryRow.available_at <= as_of_time,
            )
        ).all()
        latest = _latest_by(rows, lambda row: row.source_record_id, _master_order)
        return tuple(
            sorted(
                {
                    row.security_id
                    for row in latest.values()
                    if row.valid_from <= as_of_date
                    and (row.valid_to is None or row.valid_to > as_of_date)
                    and row.listed_on <= as_of_date
                    and (row.delisted_on is None or row.delisted_on > as_of_date)
                }
            )
        )

    def status(self, security_id: str, as_of_time: datetime) -> SecurityStatus:
        row = self._session.scalar(
            select(SecurityStatusDailyRow)
            .where(
                SecurityStatusDailyRow.security_id == security_id,
                SecurityStatusDailyRow.trade_date == as_of_time.date(),
                SecurityStatusDailyRow.available_at <= as_of_time,
            )
            .order_by(SecurityStatusDailyRow.available_at.desc(), SecurityStatusDailyRow.id.desc())
            .limit(1)
        )
        if row is None:
            raise StrictDataMissingError(f"security status missing: {security_id}")
        return SecurityStatus(row.is_st, row.is_suspended, row.board, row.price_limit_pct)

    def industry(self, security_id: str, as_of_time: datetime) -> str:
        rows = self._session.scalars(
            select(IndustryMembershipHistoryRow).where(
                IndustryMembershipHistoryRow.security_id == security_id,
                IndustryMembershipHistoryRow.available_at <= as_of_time,
            )
        ).all()
        latest = _latest_by(rows, lambda row: row.source_record_id, _available_order)
        candidates = []
        for row in latest.values():
            payload = json.loads(row.payload_json)
            effective_from = date.fromisoformat(str(payload["effective_from"]))
            effective_to_value = str(payload.get("effective_to") or "")
            effective_to = date.fromisoformat(effective_to_value) if effective_to_value else None
            if effective_from <= as_of_time.date() and (
                effective_to is None or effective_to > as_of_time.date()
            ):
                candidates.append((effective_from, row.available_at, row.id, payload))
        if not candidates:
            raise StrictDataMissingError(f"industry missing: {security_id}")
        selected = max(candidates, key=lambda item: item[:3])
        return str(selected[3]["industry_id"])


class TemporalExecutionQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def fee_schedule(
        self,
        *,
        trade_date: date,
        exchange: str,
        asset_type: str,
        as_of_time: datetime,
    ) -> FeeSchedule:
        row = self._session.scalar(
            select(FeeScheduleRow)
            .where(
                FeeScheduleRow.exchange == exchange,
                FeeScheduleRow.asset_type == asset_type,
                FeeScheduleRow.effective_from <= trade_date,
                or_(
                    FeeScheduleRow.effective_to.is_(None), FeeScheduleRow.effective_to > trade_date
                ),
                FeeScheduleRow.available_at <= as_of_time,
            )
            .order_by(
                FeeScheduleRow.effective_from.desc(),
                FeeScheduleRow.available_at.desc(),
                FeeScheduleRow.id.desc(),
            )
            .limit(1)
        )
        if row is None:
            raise StrictDataMissingError("fee schedule missing")
        return FeeSchedule(
            row.source_record_id,
            row.source_artifact_hash,
            row.commission_rate,
            row.minimum_commission,
            row.stamp_tax_sell_rate,
            row.transfer_rate,
        )


class TemporalDisclosureQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_financial(self, security_id: str, as_of_time: datetime) -> FinancialDisclosure:
        rows = self._session.scalars(
            select(FinancialDisclosureRow).where(
                FinancialDisclosureRow.security_id == security_id,
                FinancialDisclosureRow.available_at <= as_of_time,
            )
        ).all()
        if not rows:
            raise StrictDataMissingError(f"financial disclosure missing: {security_id}")
        row = max(
            rows,
            key=lambda item: (item.report_period, item.revision, item.available_at, item.id),
        )
        fact_rows = self._session.scalars(
            select(FinancialFactRow).where(
                FinancialFactRow.disclosure_id == row.id,
                FinancialFactRow.available_at <= as_of_time,
            )
        ).all()
        facts = {
            metric: fact.value
            for metric, fact in _latest_by(fact_rows, lambda item: item.metric, _fact_order).items()
        }
        return FinancialDisclosure(
            row.source_record_id,
            row.revision,
            row.published_at,
            row.available_at,
            facts,
        )

    def policies(self, as_of_time: datetime) -> tuple[PolicyDocument, ...]:
        rows = self._session.scalars(
            select(PolicyDocumentRow).where(PolicyDocumentRow.available_at <= as_of_time)
        ).all()
        latest = _latest_by(rows, lambda row: row.source_record_id, _policy_order)
        documents = []
        for document_id, row in latest.items():
            if row.available_at != max(row.published_at, row.first_observed_at):
                raise ValueError(f"policy available_at mismatch: {document_id}")
            parent = latest.get(row.official_parent_id)
            scoreable = row.evidence_grade == "A" or (
                row.evidence_grade == "B" and parent is not None and parent.evidence_grade == "A"
            )
            documents.append(
                PolicyDocument(document_id, row.available_at, row.evidence_grade, scoreable)
            )
        return tuple(sorted(documents, key=lambda item: item.document_id))


T = TypeVar("T")


def _latest_by(
    rows: list[T],
    key: Callable[[T], str],
    order: Callable[[T], tuple[object, ...]],
) -> dict[str, T]:
    result: dict[str, T] = {}
    for row in rows:
        row_key = key(row)
        current = result.get(row_key)
        if current is None or order(row) > order(current):
            result[row_key] = row
    return result


def _master_order(row: SecurityMasterHistoryRow) -> tuple[datetime, str]:
    return row.available_at, row.id


def _available_order(row: IndustryMembershipHistoryRow) -> tuple[datetime, str]:
    return row.available_at, row.id


def _fact_order(row: FinancialFactRow) -> tuple[datetime, str]:
    return row.available_at, row.id


def _policy_order(row: PolicyDocumentRow) -> tuple[datetime, str]:
    return row.available_at, row.id
