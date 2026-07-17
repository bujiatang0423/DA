from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import CandidateItem, CandidateRecommendationResult


class CandidateSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(default="default", min_length=1, max_length=64)
    as_of_time: datetime


class CandidateFactorsResponse(BaseModel):
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal


class CandidateItemResponse(BaseModel):
    security_id: str
    security_name: str
    bucket: str
    state: str
    strategy_book: str | None
    factors: CandidateFactorsResponse
    planned_quantity: int
    initial_stop: Decimal | None
    trigger_condition: str
    invalidation_condition: str
    reason_codes: tuple[str, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_domain(cls, item: CandidateItem) -> "CandidateItemResponse":
        return cls(
            security_id=item.security_id,
            security_name=item.security_name,
            bucket=item.bucket.value,
            state=item.state.value,
            strategy_book=item.strategy_book.value if item.strategy_book else None,
            factors=CandidateFactorsResponse(
                p=item.factors.p,
                f=item.factors.f,
                r=item.factors.r,
                t=item.factors.t,
                v=item.factors.v,
                s=item.factors.s,
                percentile_rank=item.factors.percentile_rank,
            ),
            planned_quantity=item.planned_quantity,
            initial_stop=item.initial_stop,
            trigger_condition=item.trigger_condition,
            invalidation_condition=item.invalidation_condition,
            reason_codes=tuple(code.value for code in item.reason_codes),
            quality_codes=item.quality_codes,
            evidence_refs=item.evidence_refs,
        )


class CandidateRecommendationResponse(BaseModel):
    run_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: str
    llm_grade: str
    market_state: str
    market_confidence: str
    quality_codes: tuple[str, ...]
    items: tuple[CandidateItemResponse, ...]
    auto_trade_enabled: Literal[False] = False
    human_confirm_required: Literal[True] = True

    @classmethod
    def from_domain(cls, result: CandidateRecommendationResult) -> "CandidateRecommendationResponse":
        return cls(
            run_id=result.run_id,
            as_of_time=result.as_of_time,
            strategy_version="v2.12",
            manifest_hash=result.manifest_hash,
            data_grade=result.data_grade.value,
            llm_grade=result.llm_grade.value,
            market_state=result.market_state,
            market_confidence=result.market_confidence,
            quality_codes=result.quality_codes,
            items=tuple(CandidateItemResponse.from_domain(item) for item in result.items),
        )
