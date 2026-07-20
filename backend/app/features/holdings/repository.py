from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from backend.app.infrastructure.persistence.models import Base
from .models import HoldingAdviceItem, HoldingAnalysisResult


class HoldingAnalysisConflict(RuntimeError):
    pass


class HoldingAnalysisNotFound(KeyError):
    pass


class HoldingAnalysisRepository(Protocol):
    def save(self, result: HoldingAnalysisResult) -> None: ...

    def get(self, run_id: str) -> HoldingAnalysisResult | None: ...

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None: ...

    def at(self, portfolio_id: str, as_of_time: datetime) -> HoldingAnalysisResult | None: ...


HoldingResultRepository = HoldingAnalysisRepository


class HoldingResultRow(Base):
    __tablename__ = "holding_analysis_results"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class HoldingAnalysisItemRow(Base):
    __tablename__ = "holding_analysis_items"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("holding_analysis_results.run_id", ondelete="CASCADE"), primary_key=True
    )
    item_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[str] = mapped_column(String(64), index=True)
    security_name: Mapped[str] = mapped_column(String(256))
    origin: Mapped[str] = mapped_column(String(64))
    strategy_book: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    available_to_sell: Mapped[int] = mapped_column(Integer)
    average_cost: Mapped[str] = mapped_column(String(64))
    close: Mapped[str] = mapped_column(String(64))
    market_state: Mapped[str] = mapped_column(String(64))
    factors: Mapped[dict[str, str]] = mapped_column(JSON)
    r_multiple: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_stop: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposed_effective_stop: Mapped[str | None] = mapped_column(String(64), nullable=True)
    advised_action: Mapped[str] = mapped_column(String(64))
    planned_quantity: Mapped[int] = mapped_column(Integer)
    pending_target_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    quality_codes: Mapped[list[str]] = mapped_column(JSON)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON)


class SqlHoldingAnalysisRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def save(self, result: HoldingAnalysisResult) -> None:
        with self._sessions.begin() as session:
            existing = session.get(HoldingResultRow, result.run_id)
            if existing is not None:
                if str(existing.payload.get("manifest_hash")) != result.manifest_hash:
                    raise HoldingAnalysisConflict(result.run_id)
                item_count = session.scalar(
                    select(func.count())
                    .select_from(HoldingAnalysisItemRow)
                    .where(HoldingAnalysisItemRow.run_id == result.run_id)
                )
                if item_count == 0:
                    session.add_all(
                        _item_row(result.run_id, item_index, item)
                        for item_index, item in enumerate(
                            sorted(result.items, key=lambda value: value.security_id)
                        )
                    )
                return
            session.add(
                HoldingResultRow(
                    run_id=result.run_id,
                    as_of_time=result.as_of_time,
                    payload=_encode(result),
                )
            )
            session.add_all(
                _item_row(result.run_id, item_index, item)
                for item_index, item in enumerate(
                    sorted(result.items, key=lambda value: value.security_id)
                )
            )

    def get(self, run_id: str) -> HoldingAnalysisResult | None:
        with self._sessions() as session:
            row = session.get(HoldingResultRow, run_id)
            return self._decode(session, row) if row else None

    def latest(self, portfolio_id: str) -> HoldingAnalysisResult | None:
        with self._sessions() as session:
            row = session.scalar(
                select(HoldingResultRow)
                .where(HoldingResultRow.payload["portfolio_id"].as_string() == portfolio_id)
                .order_by(HoldingResultRow.as_of_time.desc(), HoldingResultRow.run_id.desc())
                .limit(1)
            )
            return self._decode(session, row) if row else None

    def at(self, portfolio_id: str, as_of_time: datetime) -> HoldingAnalysisResult | None:
        with self._sessions() as session:
            row = session.scalar(
                select(HoldingResultRow)
                .where(
                    HoldingResultRow.payload["portfolio_id"].as_string() == portfolio_id,
                    HoldingResultRow.as_of_time == as_of_time,
                )
                .order_by(HoldingResultRow.run_id.desc())
                .limit(1)
            )
            return self._decode(session, row) if row else None

    @staticmethod
    def _decode(session: Session, row: HoldingResultRow) -> HoldingAnalysisResult:
        item_payloads = [
            _item_payload(item)
            for item in session.scalars(
                select(HoldingAnalysisItemRow)
                .where(HoldingAnalysisItemRow.run_id == row.run_id)
                .order_by(HoldingAnalysisItemRow.item_index)
            )
        ]
        return _decode(row.payload, item_payloads or None)


SqlHoldingResultRepository = SqlHoldingAnalysisRepository


def _encode(result: HoldingAnalysisResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "portfolio_id": result.portfolio_id,
        "as_of_time": result.as_of_time.isoformat(),
        "strategy_version": result.strategy_version,
        "manifest_hash": result.manifest_hash,
        "data_grade": result.data_grade.value,
        "llm_grade": result.llm_grade.value,
        "summary": {
            "equity": str(result.summary.equity),
            "cash": str(result.summary.cash),
            "gross_exposure_pct": str(result.summary.gross_exposure_pct),
            "portfolio_risk_pct": str(result.summary.portfolio_risk_pct),
            "market_state": result.summary.market_state,
        },
        "items": [
            _encode_item(item) for item in sorted(result.items, key=lambda value: value.security_id)
        ],
    }


def _item_row(run_id: str, item_index: int, item: HoldingAdviceItem) -> HoldingAnalysisItemRow:
    payload = _encode_item(item)
    return HoldingAnalysisItemRow(
        run_id=run_id,
        item_index=item_index,
        security_id=str(payload["security_id"]),
        security_name=str(payload["security_name"]),
        origin=str(payload["origin"]),
        strategy_book=payload["strategy_book"],
        quantity=int(payload["quantity"]),
        available_to_sell=int(payload["available_to_sell"]),
        average_cost=str(payload["average_cost"]),
        close=str(payload["close"]),
        market_state=str(payload["market_state"]),
        factors=dict(payload["factors"]),
        r_multiple=payload["r_multiple"],
        effective_stop=payload["effective_stop"],
        proposed_effective_stop=payload["proposed_effective_stop"],
        advised_action=str(payload["advised_action"]),
        planned_quantity=int(payload["planned_quantity"]),
        pending_target_action=payload["pending_target_action"],
        reason_codes=list(payload["reason_codes"]),
        quality_codes=list(payload["quality_codes"]),
        evidence_refs=list(payload["evidence_refs"]),
    )


def _encode_item(item: HoldingAdviceItem) -> dict[str, object]:
    return {
        "security_id": item.security_id,
        "security_name": item.security_name,
        "origin": item.origin.value,
        "strategy_book": item.strategy_book.value if item.strategy_book else None,
        "quantity": item.quantity,
        "available_to_sell": item.available_to_sell,
        "average_cost": str(item.average_cost),
        "close": str(item.close),
        "market_state": item.market_state,
        "factors": {
            name: str(getattr(item.factors, name))
            for name in ("p", "f", "r", "t", "v", "s", "percentile_rank")
        },
        "r_multiple": str(item.r_multiple) if item.r_multiple is not None else None,
        "effective_stop": str(item.effective_stop) if item.effective_stop is not None else None,
        "proposed_effective_stop": str(item.proposed_effective_stop)
        if item.proposed_effective_stop is not None
        else None,
        "advised_action": item.advised_action.value,
        "planned_quantity": item.planned_quantity,
        "pending_target_action": item.pending_target_action.value
        if item.pending_target_action
        else None,
        "reason_codes": [code.value for code in item.reason_codes],
        "quality_codes": list(item.quality_codes),
        "evidence_refs": list(item.evidence_refs),
    }


def _item_payload(row: HoldingAnalysisItemRow) -> dict[str, object]:
    return {
        "security_id": row.security_id,
        "security_name": row.security_name,
        "origin": row.origin,
        "strategy_book": row.strategy_book,
        "quantity": row.quantity,
        "available_to_sell": row.available_to_sell,
        "average_cost": row.average_cost,
        "close": row.close,
        "market_state": row.market_state,
        "factors": row.factors,
        "r_multiple": row.r_multiple,
        "effective_stop": row.effective_stop,
        "proposed_effective_stop": row.proposed_effective_stop,
        "advised_action": row.advised_action,
        "planned_quantity": row.planned_quantity,
        "pending_target_action": row.pending_target_action,
        "reason_codes": row.reason_codes,
        "quality_codes": row.quality_codes,
        "evidence_refs": row.evidence_refs,
    }


def _decode(
    payload: dict[str, object], item_payloads: list[dict[str, object]] | None = None
) -> HoldingAnalysisResult:
    from backend.app.contracts.grades import DataGrade, LlmGrade
    from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
    from backend.app.core.strategy.reason_codes import ReasonCode
    from .models import AdviceAction, HoldingAdviceItem, HoldingFactors, HoldingRiskSummary

    summary = dict(payload["summary"])
    items = []
    raw_items = item_payloads if item_payloads is not None else list(payload["items"])
    for raw in sorted(raw_items, key=lambda value: str(dict(value)["security_id"])):
        row = dict(raw)
        factors = dict(row["factors"])
        items.append(
            HoldingAdviceItem(
                security_id=str(row["security_id"]),
                security_name=str(row["security_name"]),
                origin=PositionOrigin(str(row["origin"])),
                strategy_book=StrategyBook(str(row["strategy_book"]))
                if row.get("strategy_book")
                else None,
                quantity=int(row["quantity"]),
                available_to_sell=int(row["available_to_sell"]),
                average_cost=Decimal(str(row["average_cost"])),
                close=Decimal(str(row["close"])),
                market_state=str(row["market_state"]),
                factors=HoldingFactors(
                    **{key: Decimal(str(value)) for key, value in factors.items()}
                ),
                r_multiple=Decimal(str(row["r_multiple"])) if row.get("r_multiple") else None,
                effective_stop=Decimal(str(row["effective_stop"]))
                if row.get("effective_stop")
                else None,
                proposed_effective_stop=Decimal(str(row["proposed_effective_stop"]))
                if row.get("proposed_effective_stop")
                else None,
                advised_action=AdviceAction(str(row["advised_action"])),
                planned_quantity=int(row["planned_quantity"]),
                pending_target_action=AdviceAction(str(row["pending_target_action"]))
                if row.get("pending_target_action")
                else None,
                reason_codes=tuple(ReasonCode(str(code)) for code in row["reason_codes"]),
                quality_codes=tuple(str(code) for code in row["quality_codes"]),
                evidence_refs=tuple(str(ref) for ref in row["evidence_refs"]),
            )
        )
    return HoldingAnalysisResult(
        run_id=str(payload["run_id"]),
        portfolio_id=str(payload["portfolio_id"]),
        as_of_time=datetime.fromisoformat(str(payload["as_of_time"])),
        strategy_version=str(payload["strategy_version"]),
        manifest_hash=str(payload["manifest_hash"]),
        data_grade=DataGrade(str(payload["data_grade"])),
        llm_grade=LlmGrade(str(payload["llm_grade"])),
        summary=HoldingRiskSummary(
            equity=Decimal(str(summary["equity"])),
            cash=Decimal(str(summary["cash"])),
            gross_exposure_pct=Decimal(str(summary["gross_exposure_pct"])),
            portfolio_risk_pct=Decimal(str(summary["portfolio_risk_pct"])),
            market_state=str(summary["market_state"]),
        ),
        items=tuple(items),
    )
