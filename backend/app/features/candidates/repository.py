from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import DateTime, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from backend.app.infrastructure.persistence.models import Base
from .models import CandidateRecommendationResult, CandidateState


class CandidateResultConflict(RuntimeError):
    pass


class CandidateRepository(Protocol):
    def save(self, result: CandidateRecommendationResult) -> None: ...

    def get(self, run_id: str) -> CandidateRecommendationResult | None: ...

    def latest(self) -> CandidateRecommendationResult | None: ...

    def states_before(self, as_of_time: datetime) -> dict[str, CandidateState]: ...


class CandidateResultRow(Base):
    __tablename__ = "candidate_results"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class SqlCandidateRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, result: CandidateRecommendationResult) -> None:
        with self._session_factory.begin() as session:
            existing = session.get(CandidateResultRow, result.run_id)
            if existing is not None:
                if existing.manifest_hash != result.manifest_hash:
                    raise CandidateResultConflict(result.run_id)
                return
            session.add(
                CandidateResultRow(
                    run_id=result.run_id,
                    as_of_time=result.as_of_time,
                    manifest_hash=result.manifest_hash,
                    payload=_encode(result),
                )
            )

    def get(self, run_id: str) -> CandidateRecommendationResult | None:
        with self._session_factory() as session:
            row = session.get(CandidateResultRow, run_id)
            return _decode(row.payload) if row else None

    def latest(self) -> CandidateRecommendationResult | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(CandidateResultRow)
                .order_by(CandidateResultRow.as_of_time.desc(), CandidateResultRow.run_id.desc())
                .limit(1)
            )
            return _decode(row.payload) if row else None

    def states_before(self, as_of_time: datetime) -> dict[str, CandidateState]:
        latest = self._latest_before(as_of_time)
        if latest is None:
            return {}
        return {item.security_id: item.state for item in latest.items}

    def _latest_before(self, as_of_time: datetime) -> CandidateRecommendationResult | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(CandidateResultRow)
                .where(CandidateResultRow.as_of_time <= as_of_time)
                .order_by(CandidateResultRow.as_of_time.desc(), CandidateResultRow.run_id.desc())
                .limit(1)
            )
            return _decode(row.payload) if row else None


def _encode(result: CandidateRecommendationResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "as_of_time": result.as_of_time.isoformat(),
        "strategy_version": result.strategy_version,
        "manifest_hash": result.manifest_hash,
        "data_grade": result.data_grade.value,
        "llm_grade": result.llm_grade.value,
        "market_state": result.market_state,
        "market_confidence": result.market_confidence,
        "quality_codes": list(result.quality_codes),
        "items": [
            {
                "security_id": item.security_id,
                "security_name": item.security_name,
                "bucket": item.bucket.value,
                "state": item.state.value,
                "strategy_book": item.strategy_book.value if item.strategy_book else None,
                "factors": {
                    "p": str(item.factors.p),
                    "f": str(item.factors.f),
                    "r": str(item.factors.r),
                    "t": str(item.factors.t),
                    "v": str(item.factors.v),
                    "s": str(item.factors.s),
                    "percentile_rank": str(item.factors.percentile_rank),
                },
                "planned_quantity": item.planned_quantity,
                "initial_stop": str(item.initial_stop) if item.initial_stop is not None else None,
                "trigger_condition": item.trigger_condition,
                "invalidation_condition": item.invalidation_condition,
                "reason_codes": [code.value for code in item.reason_codes],
                "quality_codes": list(item.quality_codes),
                "evidence_refs": list(item.evidence_refs),
            }
            for item in result.items
        ],
    }


def _decode(payload: dict[str, object]) -> CandidateRecommendationResult:
    from backend.app.contracts.grades import DataGrade, LlmGrade
    from backend.app.core.portfolio.models import StrategyBook
    from backend.app.core.strategy.reason_codes import ReasonCode
    from .models import CandidateBucket, CandidateFactors, CandidateItem

    items = []
    for raw in payload.get("items", []):
        row = dict(raw)
        factors = dict(row["factors"])
        items.append(
            CandidateItem(
                security_id=str(row["security_id"]),
                security_name=str(row["security_name"]),
                bucket=CandidateBucket(str(row["bucket"])),
                state=CandidateState(str(row["state"])),
                strategy_book=(
                    StrategyBook(str(row["strategy_book"])) if row.get("strategy_book") else None
                ),
                factors=CandidateFactors(
                    **{key: _decimal(value) for key, value in factors.items()}
                ),
                planned_quantity=int(row["planned_quantity"]),
                initial_stop=_decimal(row["initial_stop"]) if row.get("initial_stop") else None,
                trigger_condition=str(row["trigger_condition"]),
                invalidation_condition=str(row["invalidation_condition"]),
                reason_codes=tuple(ReasonCode(str(code)) for code in row["reason_codes"]),
                quality_codes=tuple(str(code) for code in row["quality_codes"]),
                evidence_refs=tuple(str(ref) for ref in row["evidence_refs"]),
            )
        )
    return CandidateRecommendationResult(
        run_id=str(payload["run_id"]),
        as_of_time=datetime.fromisoformat(str(payload["as_of_time"])),
        strategy_version="v2.12",
        manifest_hash=str(payload["manifest_hash"]),
        data_grade=DataGrade(str(payload["data_grade"])),
        llm_grade=LlmGrade(str(payload["llm_grade"])),
        market_state=str(payload["market_state"]),
        market_confidence=str(payload["market_confidence"]),
        quality_codes=tuple(str(code) for code in payload["quality_codes"]),
        items=tuple(items),
    )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))
