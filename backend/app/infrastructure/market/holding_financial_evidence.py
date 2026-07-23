"""Refresh official financial announcements for the current holding scope."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from backend.app.infrastructure.market.official_evidence import (
    FINANCIAL_ANNOUNCEMENT,
    OfficialEvidenceDocument,
    OfficialEvidenceReader,
    OfficialEvidenceStore,
)


@dataclass(frozen=True)
class FinancialAnnouncementReference:
    security_id: str
    report_period: date
    issuer: str
    title: str
    published_at: datetime
    source_url: str


@dataclass(frozen=True)
class FinancialEvidenceRefreshResult:
    available_at: datetime | None


class OfficialFinancialAnnouncementClient(Protocol):
    """Lists and downloads individual financial reports from an official source."""

    def list_financial_announcements(
        self,
        *,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[FinancialAnnouncementReference, ...]: ...

    def download_text(self, reference: FinancialAnnouncementReference) -> str: ...


class FinancialEvidenceRefreshError(RuntimeError):
    """Raised when a required official announcement cannot be verified and imported."""

    code = "HOLDING_MARKET_DATA_MISSING"


class HoldingFinancialEvidenceRefresher:
    """Imports unseen stock reports; ETFs deliberately have no company-report requirement."""

    def __init__(
        self,
        store: OfficialEvidenceStore,
        client: OfficialFinancialAnnouncementClient,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._client = client
        self._now = now

    def refresh(
        self, *, security_ids: tuple[str, ...], as_of_time: datetime
    ) -> FinancialEvidenceRefreshResult:
        retrieved_at = self._now()
        _require_aware(retrieved_at, "retrieved_at")
        _require_aware(as_of_time, "as_of_time")
        available_at: datetime | None = None
        for security_id in sorted(set(security_ids)):
            if _is_etf(security_id):
                continue
            existing_periods = _existing_report_periods(
                self._store,
                security_id=security_id,
                as_of_time=max(as_of_time, retrieved_at),
            )
            try:
                references = self._client.list_financial_announcements(
                    security_id=security_id,
                    as_of_time=as_of_time,
                )
            except Exception as exc:
                raise FinancialEvidenceRefreshError(
                    f"official financial announcement lookup failed for {security_id}"
                ) from exc
            visible_references = tuple(
                reference for reference in references if reference.published_at <= as_of_time
            )
            if not visible_references:
                raise FinancialEvidenceRefreshError(
                    f"no visible official financial announcement for {security_id}"
                )
            reference = max(
                visible_references,
                key=lambda item: (item.report_period, item.published_at, item.source_url),
            )
            if reference.security_id != security_id:
                raise FinancialEvidenceRefreshError("official announcement security mismatch")
            if reference.report_period in existing_periods:
                continue
            try:
                text = self._client.download_text(reference).strip()
                if not text:
                    raise FinancialEvidenceRefreshError(
                        f"official announcement text is empty for {security_id}"
                    )
                self._store.import_document(
                    OfficialEvidenceDocument(
                        kind=FINANCIAL_ANNOUNCEMENT,
                        source_url=reference.source_url,
                        content_sha256="calculated by OfficialEvidenceStore",
                        published_at=reference.published_at,
                        first_observed_at=max(reference.published_at, retrieved_at),
                        reviewed_at=max(reference.published_at, retrieved_at),
                        security_id=reference.security_id,
                        report_period=reference.report_period,
                        issuer=reference.issuer,
                        effective_at=reference.published_at,
                        security_ids=(),
                        title=reference.title,
                        text=text,
                    )
                )
                available_at = retrieved_at
            except FinancialEvidenceRefreshError:
                raise
            except Exception as exc:
                raise FinancialEvidenceRefreshError(
                    f"official financial announcement import failed for {security_id}"
                ) from exc
        return FinancialEvidenceRefreshResult(available_at)


def _existing_report_periods(
    store: OfficialEvidenceReader,
    *,
    security_id: str,
    as_of_time: datetime,
) -> frozenset[date]:
    return frozenset(
        document.report_period
        for document in store.documents(as_of_time=as_of_time, security_ids=(security_id,))
        if document.kind == FINANCIAL_ANNOUNCEMENT and document.report_period is not None
    )


def _is_etf(security_id: str) -> bool:
    code, _, exchange = security_id.upper().partition(".")
    return (exchange == "SH" and code.startswith("5")) or (
        exchange == "SZ" and code.startswith(("15", "16", "18"))
    )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinancialEvidenceRefreshError(f"{label} must be timezone-aware")
