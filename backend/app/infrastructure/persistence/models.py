from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
class Base(DeclarativeBase): pass
class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("kind", "idempotency_key", name="uq_runs_kind_idempotency"), Index("ix_runs_claim", "status", "submitted_at"))
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(64)); status: Mapped[str] = mapped_column(String(16)); request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True); stage: Mapped[str | None] = mapped_column(String(64), nullable=True); progress: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True)); started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True); heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True); finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True); retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
class RunEventRow(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(primary_key=True); run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True); occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True)); event_type: Mapped[str] = mapped_column(String(64)); payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
class RunArtifactRow(Base):
    __tablename__ = "run_artifacts"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4); run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True); kind: Mapped[str] = mapped_column(String(64)); relative_path: Mapped[str] = mapped_column(Text); sha256: Mapped[str] = mapped_column(String(64)); media_type: Mapped[str] = mapped_column(String(128)); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
