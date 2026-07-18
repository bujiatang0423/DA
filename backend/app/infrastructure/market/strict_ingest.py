from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.market.strict_bundle import PitBundleFile, PitBundleManifest
from backend.app.infrastructure.market.strict_row_mapping import parse_temporal_rows
from backend.app.infrastructure.persistence.strict_pit_rows import (
    DailyBarRawRow,
    IndexDailyBarRow,
    PitBundleRow,
    SecurityMasterHistoryRow,
    SecurityStatusDailyRow,
    TradingCalendarRow,
)


class StrictPitIngestor:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest(self, bundle: PitBundleManifest) -> bool:
        existing = self._session.scalar(
            select(PitBundleRow).where(PitBundleRow.manifest_sha256 == bundle.manifest_sha256)
        )
        if existing is not None:
            return False

        rows = self._parse_bundle(bundle)
        with self._session.begin_nested():
            self._session.add(
                PitBundleRow(
                    id=bundle.bundle_id,
                    manifest_sha256=bundle.manifest_sha256,
                    coverage_start=bundle.coverage_start,
                    coverage_end=bundle.coverage_end,
                )
            )
            for dataset_rows in rows:
                self._session.add_all(dataset_rows)
            self._session.flush()
        return True

    def _parse_bundle(self, bundle: PitBundleManifest) -> list[list[object]]:
        parsers = {
            "security_master_history": self._security_master,
            "security_status_daily": self._security_status,
            "trading_calendar": self._trading_calendar,
            "daily_bars_raw": self._daily_bars,
            "index_daily_bars": self._index_bars,
        }
        parsed: list[list[object]] = []
        for item in bundle.files:
            parser = parsers.get(item.dataset, self._temporal_rows)
            rows = parser(item)
            if len(rows) != item.row_count:
                raise ValueError(f"row_count mismatch: {item.dataset}")
            parsed.append(rows)
        return parsed

    @staticmethod
    def _read(item: PitBundleFile) -> list[dict[str, str]]:
        with item.path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def _security_master(self, item: PitBundleFile) -> list[object]:
        dataset = item.dataset
        return [
            SecurityMasterHistoryRow(
                id=_required(row, "record_id", dataset),
                security_id=_required(row, "security_id", dataset),
                name=_required(row, "name", dataset),
                listed_on=_date(row, "listed_on", dataset),
                delisted_on=_optional_date(row, "delisted_on", dataset),
                valid_from=_date(row, "valid_from", dataset),
                valid_to=_optional_date(row, "valid_to", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in self._read(item)
        ]

    def _security_status(self, item: PitBundleFile) -> list[object]:
        dataset = item.dataset
        return [
            SecurityStatusDailyRow(
                id=_required(row, "record_id", dataset),
                security_id=_required(row, "security_id", dataset),
                trade_date=_date(row, "trade_date", dataset),
                is_st=_boolean(row, "is_st", dataset),
                is_suspended=_boolean(row, "is_suspended", dataset),
                board=_required(row, "board", dataset),
                price_limit_pct=_decimal(row, "price_limit_pct", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in self._read(item)
        ]

    def _trading_calendar(self, item: PitBundleFile) -> list[object]:
        dataset = item.dataset
        return [
            TradingCalendarRow(
                id=_required(row, "record_id", dataset),
                exchange=_required(row, "exchange", dataset),
                trade_date=_date(row, "trade_date", dataset),
                is_open=_boolean(row, "is_open", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in self._read(item)
        ]

    def _daily_bars(self, item: PitBundleFile) -> list[object]:
        dataset = item.dataset
        return [
            DailyBarRawRow(
                id=_required(row, "record_id", dataset),
                security_id=_required(row, "security_id", dataset),
                trade_date=_date(row, "trade_date", dataset),
                open=_decimal(row, "open", dataset),
                high=_decimal(row, "high", dataset),
                low=_decimal(row, "low", dataset),
                close=_decimal(row, "close", dataset),
                volume=_integer(row, "volume", dataset),
                amount=_decimal(row, "amount", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in self._read(item)
        ]

    def _index_bars(self, item: PitBundleFile) -> list[object]:
        dataset = item.dataset
        return [
            IndexDailyBarRow(
                id=_required(row, "record_id", dataset),
                index_id=_required(row, "index_id", dataset),
                trade_date=_date(row, "trade_date", dataset),
                open=_decimal(row, "open", dataset),
                high=_decimal(row, "high", dataset),
                low=_decimal(row, "low", dataset),
                close=_decimal(row, "close", dataset),
                volume=_integer(row, "volume", dataset),
                amount=_decimal(row, "amount", dataset),
                available_at=_datetime(row, "available_at", dataset),
                source_artifact_hash=_required(row, "source_artifact_hash", dataset),
            )
            for row in self._read(item)
        ]

    def _temporal_rows(self, item: PitBundleFile) -> list[object]:
        return parse_temporal_rows(item.dataset, self._read(item))


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
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{dataset}.{field} is not a decimal") from error


def _boolean(row: dict[str, str], field: str, dataset: str) -> bool:
    value = _required(row, field, dataset).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{dataset}.{field} is not a boolean")
