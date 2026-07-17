from datetime import UTC, datetime
from decimal import Decimal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.features.holdings.models import (
    AdviceAction,
    HoldingAdviceItem,
    HoldingAnalysisResult,
    HoldingFactors,
    HoldingRiskSummary,
)


def holding_advice_item(
    security_id: str = "000001.SZ",
    *,
    origin: PositionOrigin = PositionOrigin.RECORDED_TRADE,
    strategy_book: StrategyBook | None = StrategyBook.CORE,
) -> HoldingAdviceItem:
    return HoldingAdviceItem(
        security_id=security_id,
        security_name=f"Security {security_id}",
        origin=origin,
        strategy_book=strategy_book,
        quantity=500,
        available_to_sell=400,
        average_cost=Decimal("10.20"),
        close=Decimal("10.80"),
        market_state="neutral",
        factors=HoldingFactors(
            p=Decimal("70"),
            f=Decimal("65"),
            r=Decimal("60"),
            t=Decimal("55"),
            v=Decimal("50"),
            s=Decimal("62.5"),
            percentile_rank=Decimal("0.80"),
        ),
        r_multiple=Decimal("1.50"),
        effective_stop=Decimal("9.50"),
        proposed_effective_stop=Decimal("9.80"),
        advised_action=AdviceAction.RAISE_STOP,
        planned_quantity=0,
        pending_target_action=None,
        reason_codes=(ReasonCode.ELIGIBLE,),
        quality_codes=("PRICE_PIT_VERIFIED",),
        evidence_refs=(f"market-close:{security_id}:2026-07-17",),
    )


def holding_analysis_result(
    run_id: str = "holding-run-1",
    *,
    portfolio_id: str = "default",
    as_of_time: datetime = datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
    manifest_hash: str = "manifest-sha256-abc123",
    items: tuple[HoldingAdviceItem, ...] | None = None,
) -> HoldingAnalysisResult:
    resolved_items = items or (
        holding_advice_item("600000.SH", origin=PositionOrigin.LEGACY_OPENING_BALANCE),
        holding_advice_item("000001.SZ"),
    )
    return HoldingAnalysisResult(
        run_id=run_id,
        portfolio_id=portfolio_id,
        as_of_time=as_of_time,
        strategy_version="v2.12",
        manifest_hash=manifest_hash,
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.NOT_USED,
        summary=HoldingRiskSummary(
            equity=Decimal("1000000"),
            cash=Decimal("350000"),
            gross_exposure_pct=Decimal("65.00"),
            portfolio_risk_pct=Decimal("1.25"),
            market_state="neutral",
        ),
        items=resolved_items,
    )
