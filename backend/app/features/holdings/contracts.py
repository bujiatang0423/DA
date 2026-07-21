from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.app.core.portfolio.models import PortfolioPosition, PortfolioSnapshot

from .models import (
    HoldingAdviceItem,
    HoldingAnalysisResult,
    HoldingFactors,
    HoldingRiskSummary,
)


class HoldingAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    as_of_time: AwareDatetime
    import_batch_id: str | None = Field(default=None, min_length=1, max_length=64)
    import_manifest_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class CorrectedPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    security_id: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=0)
    average_cost: Decimal = Field(ge=0)
    effective_at: AwareDatetime


class PositionCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=200)
    positions: tuple[CorrectedPositionRequest, ...] = Field(min_length=1)


class ManualFillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0)
    security_id: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    executed_at: AwareDatetime


class PortfolioPositionResponse(BaseModel):
    security_id: str
    origin: str
    strategy_book: str | None
    quantity: int
    available_to_sell: int
    average_cost: Decimal
    effective_stop: Decimal | None
    highest_close: Decimal | None
    entry_score: Decimal | None
    initial_risk_per_share: Decimal | None
    add_count: int

    @classmethod
    def from_domain(cls, position: PortfolioPosition) -> "PortfolioPositionResponse":
        return cls(
            security_id=position.security_id,
            origin=position.origin.value,
            strategy_book=position.strategy_book.value if position.strategy_book else None,
            quantity=position.quantity,
            available_to_sell=position.available_to_sell,
            average_cost=position.average_cost,
            effective_stop=position.effective_stop,
            highest_close=position.highest_close,
            entry_score=position.entry_score,
            initial_risk_per_share=position.initial_risk_per_share,
            add_count=position.add_count,
        )


class LegacyImportProvenanceResponse(BaseModel):
    batch_id: str
    manifest_sha256: str


class PortfolioPositionPage(BaseModel):
    portfolio_id: str
    as_of_time: datetime
    version: int
    cash: Decimal
    equity: Decimal
    items: tuple[PortfolioPositionResponse, ...]
    import_provenance: LegacyImportProvenanceResponse | None = None

    @classmethod
    def from_domain(
        cls,
        snapshot: PortfolioSnapshot,
        import_provenance: LegacyImportProvenanceResponse | None = None,
    ) -> "PortfolioPositionPage":
        return cls(
            portfolio_id=snapshot.portfolio_id,
            as_of_time=snapshot.as_of_time,
            version=snapshot.version,
            cash=snapshot.cash,
            equity=snapshot.equity,
            items=tuple(
                PortfolioPositionResponse.from_domain(position) for position in snapshot.positions
            ),
            import_provenance=import_provenance,
        )


class HoldingFactorsResponse(BaseModel):
    p: Decimal
    f: Decimal
    r: Decimal
    t: Decimal
    v: Decimal
    s: Decimal
    percentile_rank: Decimal

    @classmethod
    def from_domain(cls, factors: HoldingFactors) -> "HoldingFactorsResponse":
        return cls(
            p=factors.p,
            f=factors.f,
            r=factors.r,
            t=factors.t,
            v=factors.v,
            s=factors.s,
            percentile_rank=factors.percentile_rank,
        )


class HoldingRiskSummaryResponse(BaseModel):
    equity: Decimal
    cash: Decimal
    gross_exposure_pct: Decimal
    portfolio_risk_pct: Decimal
    market_state: str

    @classmethod
    def from_domain(cls, summary: HoldingRiskSummary) -> "HoldingRiskSummaryResponse":
        return cls(
            equity=summary.equity,
            cash=summary.cash,
            gross_exposure_pct=summary.gross_exposure_pct,
            portfolio_risk_pct=summary.portfolio_risk_pct,
            market_state=summary.market_state,
        )


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
    factors: HoldingFactorsResponse
    r_multiple: Decimal | None
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
            factors=HoldingFactorsResponse.from_domain(item.factors),
            r_multiple=item.r_multiple,
            advised_action=item.advised_action.value,
            planned_quantity=item.planned_quantity,
            pending_target_action=item.pending_target_action.value
            if item.pending_target_action
            else None,
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
    summary: HoldingRiskSummaryResponse
    items: tuple[HoldingAdviceItemResponse, ...]
    portfolio_imports: tuple["HoldingImportProvenanceResponse", ...]
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
            summary=HoldingRiskSummaryResponse.from_domain(result.summary),
            items=tuple(HoldingAdviceItemResponse.from_domain(item) for item in result.items),
            portfolio_imports=tuple(
                HoldingImportProvenanceResponse(
                    batch_id=provenance.batch_id,
                    manifest_sha256=provenance.manifest_sha256,
                )
                for provenance in result.portfolio_imports
            ),
        )


class HoldingImportProvenanceResponse(BaseModel):
    batch_id: str
    manifest_sha256: str
