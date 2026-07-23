from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class OfficialEvidenceRow(Base):
    """Append-only, manually reviewed official documents used by holding research."""

    __tablename__ = "official_research_evidence"
    __table_args__ = (
        UniqueConstraint("content_sha256", name="uq_official_research_evidence_hash"),
        Index("ix_official_evidence_holding_lookup", "kind", "security_id", "published_at"),
        Index("ix_official_evidence_policy_lookup", "kind", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32))
    security_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    report_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_host: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
