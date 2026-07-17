from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .models import HoldingAdviceItem, HoldingAnalysisResult


class HoldingAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    as_of_time: AwareDatetime


class HoldingAdviceItemResponse(BaseModel):
    security_id: str
    security_name: str
    origin: str
    strategy_book: str | None
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    close: Decimal
    market_state: str
    advised_action: str
    planned_quantity: int
    pending_target_action: str | None
    effective_stop: Decimal | None
    proposed_effective_stop: Decimal | None
    reason_codes: tuple[str, ...]
    quality_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_domain(cls, item: HoldingAdviceItem) -> "HoldingAdviceItemResponse":
        return cls(
            security_id=item.security_id,
            security_name=item.security_name,
            origin=item.origin.value,
            strategy_book=item.strategy_book.value if item.strategy_book else None,
            quantity=item.quantity,
            available_to_sell=item.available_to_sell,
            average_cost=item.average_cost,
            close=item.close,
            market_state=item.market_state,
            advised_action=item.advised_action.value,
            planned_quantity=item.planned_quantity,
            pending_target_action=item.pending_target_action.value
            if item.pending_target_action else None,
            effective_stop=item.effective_stop,
            proposed_effective_stop=item.proposed_effective_stop,
            reason_codes=tuple(code.value for code in item.reason_codes),
            quality_codes=item.quality_codes,
            evidence_refs=item.evidence_refs,
        )


class HoldingAnalysisResponse(BaseModel):
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"]
    manifest_hash: str
    data_grade: str
    llm_grade: str
    items: tuple[HoldingAdviceItemResponse, ...]
    auto_trade_enabled: Literal[False] = False
    human_confirm_required: Literal[True] = True

    @classmethod
    def from_domain(cls, result: HoldingAnalysisResult) -> "HoldingAnalysisResponse":
        return cls(
            run_id=result.run_id,
            portfolio_id=result.portfolio_id,
            as_of_time=result.as_of_time,
            strategy_version="v2.12",
            manifest_hash=result.manifest_hash,
            data_grade=result.data_grade.value,
            llm_grade=result.llm_grade.value,
            items=tuple(HoldingAdviceItemResponse.from_domain(item) for item in result.items),
        )
