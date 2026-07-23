"""Persisted, official evidence seam for holding analysis.

This module intentionally imports documents only.  It neither crawls public sites
nor substitutes fixture or vendor data when an official document is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch
from backend.app.infrastructure.persistence.official_evidence_rows import OfficialEvidenceRow


FINANCIAL_ANNOUNCEMENT = "financial_announcement"
POLICY_DOCUMENT = "policy_document"
_VALID_KINDS = frozenset((FINANCIAL_ANNOUNCEMENT, POLICY_DOCUMENT))
_FINANCIAL_HOSTS = frozenset(("cninfo.com.cn",))
_POLICY_HOSTS = frozenset(("csrc.gov.cn", "gov.cn", "sse.com.cn", "szse.cn"))
_DEFAULT_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class OfficialEvidenceDocument:
    kind: str
    source_url: str
    content_sha256: str
    published_at: datetime
    first_observed_at: datetime
    reviewed_at: datetime
    security_id: str | None
    report_period: date | None
    issuer: str
    effective_at: datetime
    security_ids: tuple[str, ...]
    title: str
    text: str


class OfficialEvidenceReader(Protocol):
    def documents(
        self, *, as_of_time: datetime, security_ids: tuple[str, ...]
    ) -> tuple[OfficialEvidenceDocument, ...]: ...


class OfficialEvidenceStore:
    """SQL-backed import and read store with a test-only in-memory constructor."""

    def __init__(
        self,
        sessions: sessionmaker[Session] | None = None,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self._sessions = sessions
        self._timezone = timezone or _DEFAULT_TIMEZONE
        self._documents: list[OfficialEvidenceDocument] | None = [] if sessions is None else None

    @classmethod
    def in_memory(cls) -> OfficialEvidenceStore:
        return cls()

    def import_document(self, document: OfficialEvidenceDocument) -> None:
        host = _validate_document(document)
        document = replace(document, content_sha256=_content_hash(document.text))
        if self._documents is not None:
            if any(item.content_sha256 == document.content_sha256 for item in self._documents):
                return
            self._documents.append(document)
            return
        assert self._sessions is not None
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(OfficialEvidenceRow).where(
                    OfficialEvidenceRow.content_sha256 == document.content_sha256
                )
            )
            if existing is None:
                session.add(_row_from_document(document, host))

    def documents(
        self, *, as_of_time: datetime, security_ids: tuple[str, ...]
    ) -> tuple[OfficialEvidenceDocument, ...]:
        _require_aware(as_of_time, "as_of_time")
        if self._documents is not None:
            documents = tuple(self._documents)
        else:
            assert self._sessions is not None
            with self._sessions() as session:
                rows = session.scalars(select(OfficialEvidenceRow)).all()
            documents = tuple(_document_from_row(row, self._timezone) for row in rows)
        return tuple(
            document
            for document in documents
            if _is_available(document, as_of_time)
            and (
                (
                    document.kind == POLICY_DOCUMENT
                    and bool(set(document.security_ids) & set(security_ids))
                )
                or (
                    document.kind == FINANCIAL_ANNOUNCEMENT
                    and document.security_id in security_ids
                )
            )
        )


class OfficialEvidenceSource:
    """Translate only persisted, reviewed official documents into PIT records."""

    provider = "official_evidence_store"

    def __init__(self, store: OfficialEvidenceReader) -> None:
        self._store = store

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        records = tuple(
            record
            for document in self._store.documents(
                as_of_time=as_of_time,
                security_ids=scope.security_ids,
            )
            for record in _record(document)
        )
        lineage = tuple(
            LineageRef(
                batch_id=f"official-{record.source_artifact_hash[:16]}",
                provider=self.provider,
                source_artifact_hash=record.source_artifact_hash,
            )
            for record in records
        )
        return ResearchBatch(records, lineage)


def _record(document: OfficialEvidenceDocument) -> TemporalRecord:
    kind = (
        DataKind.FINANCIAL_DISCLOSURE
        if document.kind == FINANCIAL_ANNOUNCEMENT
        else DataKind.POLICY_DOCUMENT
    )
    entity_ids = (
        (document.security_id,)
        if document.kind == FINANCIAL_ANNOUNCEMENT
        else document.security_ids
    )
    suffix = (
        f"{document.report_period.isoformat()}:{document.content_sha256[:16]}"
        if document.report_period
        else document.content_sha256
    )
    available_at = max(document.published_at, document.first_observed_at)
    return tuple(
        TemporalRecord(
            record_id=f"{kind.value}:{entity_id}:{suffix}",
            kind=kind,
            entity_id=entity_id,
            event_time=document.effective_at,
            observed_at=document.first_observed_at,
            available_at=available_at,
            source_artifact_hash=document.content_sha256,
            payload={
                "source_url": document.source_url,
                "issuer": document.issuer,
                "published_at": document.published_at.isoformat(),
                "effective_at": document.effective_at.isoformat(),
                "first_observed_at": document.first_observed_at.isoformat(),
                "reviewed_at": document.reviewed_at.isoformat(),
                "security_ids": document.security_ids,
                "title": document.title,
                "text": document.text,
            },
        )
        for entity_id in entity_ids
    )


def _validate_document(document: OfficialEvidenceDocument) -> str:
    if document.kind not in _VALID_KINDS:
        raise ValueError(f"unsupported official evidence kind: {document.kind}")
    host = _official_host(document.kind, document.source_url)
    for value, label in (
        (document.published_at, "published_at"),
        (document.first_observed_at, "first_observed_at"),
        (document.reviewed_at, "reviewed_at"),
        (document.effective_at, "effective_at"),
    ):
        _require_aware(value, label)
    if document.first_observed_at < document.published_at:
        raise ValueError("first_observed_at cannot precede published_at")
    if document.reviewed_at < document.first_observed_at:
        raise ValueError("reviewed_at cannot precede first_observed_at")
    if document.kind == FINANCIAL_ANNOUNCEMENT and (
        document.security_id is None or document.report_period is None
    ):
        raise ValueError("financial announcement requires security_id and report_period")
    if document.kind == POLICY_DOCUMENT and (
        document.security_id is not None or document.report_period is not None
    ):
        raise ValueError("policy document cannot be security-specific")
    if document.kind == POLICY_DOCUMENT and not document.security_ids:
        raise ValueError("policy document requires applicable security_ids")
    if document.kind == FINANCIAL_ANNOUNCEMENT and document.security_ids:
        raise ValueError("financial announcement cannot declare policy security_ids")
    if not document.issuer.strip():
        raise ValueError("issuer is required")
    return host


def _official_host(kind: str, source_url: str) -> str:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    allowed_hosts = _FINANCIAL_HOSTS if kind == FINANCIAL_ANNOUNCEMENT else _POLICY_HOSTS
    if parsed.scheme != "https" or not any(
        host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts
    ):
        label = "financial announcement" if kind == FINANCIAL_ANNOUNCEMENT else "policy document"
        raise ValueError(f"source URL is not on the official allowlist for {label}")
    return host


def _is_available(document: OfficialEvidenceDocument, as_of_time: datetime) -> bool:
    return max(document.published_at, document.first_observed_at, document.effective_at) <= as_of_time


def _document_from_row(row: OfficialEvidenceRow, timezone: ZoneInfo) -> OfficialEvidenceDocument:
    return OfficialEvidenceDocument(
        kind=row.kind,
        source_url=row.source_url,
        content_sha256=row.content_sha256,
        published_at=_aware(row.published_at, timezone),
        first_observed_at=_aware(row.first_observed_at, timezone),
        reviewed_at=_aware(row.reviewed_at, timezone),
        security_id=row.security_id,
        report_period=row.report_period,
        issuer=row.issuer,
        effective_at=_aware(row.effective_at, timezone),
        security_ids=tuple(row.security_ids),
        title=row.title,
        text=row.text,
    )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _aware(value: datetime, timezone: ZoneInfo) -> datetime:
    return value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone)


def _content_hash(text: str) -> str:
    from hashlib import sha256

    return sha256(text.encode("utf-8")).hexdigest()


def _row_from_document(document: OfficialEvidenceDocument, host: str) -> OfficialEvidenceRow:
    return OfficialEvidenceRow(
        source_host=host,
        kind=document.kind,
        security_id=document.security_id,
        report_period=document.report_period,
        issuer=document.issuer,
        effective_at=document.effective_at,
        security_ids=list(document.security_ids),
        source_url=document.source_url,
        content_sha256=document.content_sha256,
        published_at=document.published_at,
        first_observed_at=document.first_observed_at,
        reviewed_at=document.reviewed_at,
        title=document.title,
        text=document.text,
    )
