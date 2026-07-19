from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class BacktestResultRow(Base):
    __tablename__ = "backtest_results"

    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    strategy_version: Mapped[str] = mapped_column(String(128))
    input_manifest_hash: Mapped[str] = mapped_column(String(64), index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))


class BacktestGroupResultRow(Base):
    __tablename__ = "backtest_group_results"
    __table_args__ = (UniqueConstraint("run_id", "group", name="uq_backtest_group_result"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
        index=True,
    )
    group: Mapped[str] = mapped_column(String(1))
    data_grade: Mapped[str] = mapped_column(String(32))
    llm_grade: Mapped[str] = mapped_column(String(32))
    input_manifest_hash: Mapped[str] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metric_details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    comparison_inputs: Mapped[dict[str, str]] = mapped_column(JSONB)
    out_of_sample_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSONB)


class BacktestCurvePointRow(Base):
    __tablename__ = "backtest_curve_points"
    __table_args__ = (
        UniqueConstraint("run_id", "group", "ordinal", name="uq_backtest_curve_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
        index=True,
    )
    group: Mapped[str] = mapped_column(String(1))
    ordinal: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, str]] = mapped_column(JSONB)


class BacktestTradeRow(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (UniqueConstraint("run_id", "group", "ordinal", name="uq_backtest_trade"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
        index=True,
    )
    group: Mapped[str] = mapped_column(String(1))
    ordinal: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, str]] = mapped_column(JSONB)


class BacktestRejectedAttemptRow(Base):
    __tablename__ = "backtest_rejected_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "group", "ordinal", name="uq_backtest_rejected_attempt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_results.run_id", ondelete="CASCADE"),
        index=True,
    )
    group: Mapped[str] = mapped_column(String(1))
    ordinal: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, str]] = mapped_column(JSONB)
