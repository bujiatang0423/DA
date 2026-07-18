from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from backend.app.infrastructure.persistence.strict_pit_rows import (
    AdjustmentFactorRow,
    CorporateActionRow,
    FeeScheduleRow,
    FinancialDisclosureRow,
    FinancialFactRow,
    IndustryMembershipHistoryRow,
    PolicyDocumentRow,
    ThemeMembershipHistoryRow,
)

TEMPORAL_TYPES = {
    "corporate_actions": CorporateActionRow,
    "adjustment_factors": AdjustmentFactorRow,
    "industry_membership_history": IndustryMembershipHistoryRow,
    "theme_membership_history": ThemeMembershipHistoryRow,
}


def parse_temporal_rows(dataset: str, rows: list[dict[str, str]]) -> list[object]:
    if dataset in TEMPORAL_TYPES:
        row_type = TEMPORAL_TYPES[dataset]
        return [
            row_type(
                id=_required(row, "record_id", dataset),
                security_id=_required(row, "security_id", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
                payload_json=json.dumps(row, ensure_ascii=True, sort_keys=True),
            )
            for row in rows
        ]
    if dataset == "financial_disclosures":
        return [
            FinancialDisclosureRow(
                id=_required(row, "disclosure_id", dataset),
                security_id=_required(row, "security_id", dataset),
                report_period=_date(row, "report_period", dataset),
                revision=_integer(row, "revision", dataset),
                published_at=_datetime(row, "published_at", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "financial_facts":
        return [
            FinancialFactRow(
                id=_required(row, "record_id", dataset),
                disclosure_id=_required(row, "disclosure_id", dataset),
                metric=_required(row, "metric", dataset),
                value=_required(row, "value", dataset),
                unit=_required(row, "unit", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "policy_documents":
        return [
            PolicyDocumentRow(
                id=_required(row, "document_id", dataset),
                published_at=_datetime(row, "published_at", dataset),
                first_observed_at=_datetime(row, "first_observed_at", dataset),
                available_at=_datetime(row, "available_at", dataset),
                evidence_grade=_required(row, "evidence_grade", dataset),
                official_parent_id=row.get("official_parent_id") or None,
                content_hash=_required(row, "content_hash", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    if dataset == "fee_schedules":
        return [
            FeeScheduleRow(
                id=_required(row, "record_id", dataset),
                effective_from=_date(row, "effective_from", dataset),
                effective_to=_optional_date(row, "effective_to", dataset),
                exchange=_required(row, "exchange", dataset),
                asset_type=_required(row, "asset_type", dataset),
                commission_rate=_decimal(row, "commission_rate", dataset),
                minimum_commission=_decimal(row, "minimum_commission", dataset),
                stamp_tax_sell_rate=_decimal(row, "stamp_tax_sell_rate", dataset),
                transfer_rate=_decimal(row, "transfer_rate", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in rows
        ]
    raise ValueError(f"unsupported strict dataset: {dataset}")


def _required(row: dict[str, str], field: str, dataset: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"{dataset}.{field} is required")
    return value


def _date(row: dict[str, str], field: str, dataset: str) -> date:
    try:
        return date.fromisoformat(_required(row, field, dataset))
    except ValueError as error:
        raise ValueError(f"{dataset}.{field} is not a date") from error


def _optional_date(row: dict[str, str], field: str, dataset: str) -> date | None:
    if not row.get(field):
        return None
    return _date(row, field, dataset)


def _datetime(row: dict[str, str], field: str, dataset: str) -> datetime:
    try:
        return datetime.fromisoformat(_required(row, field, dataset))
    except ValueError as error:
        raise ValueError(f"{dataset}.{field} is not a datetime") from error


def _integer(row: dict[str, str], field: str, dataset: str) -> int:
    try:
        return int(_required(row, field, dataset))
    except ValueError as error:
        raise ValueError(f"{dataset}.{field} is not an integer") from error


def _decimal(row: dict[str, str], field: str, dataset: str) -> Decimal:
    try:
        return Decimal(_required(row, field, dataset))
    except ValueError as error:
        raise ValueError(f"{dataset}.{field} is not a decimal") from error
