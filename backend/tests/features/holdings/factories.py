from datetime import UTC, date, datetime
from decimal import Decimal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import (
    PointInTimeSnapshot,
    QualityIssue,
    SnapshotQuality,
    SnapshotScope,
)
from backend.app.core.portfolio.models import (
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
    StrategyBook,
)
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.core.strategy.types import (
    ConstraintDecision,
    FactorScores,
    FinancialLight,
    MarketRegimeDecision,
    MarketState,
    PortfolioView,
    SecurityEvaluation,
    StrategyEvaluation,
)
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
        holding_advice_item(
            "600000.SH",
            origin=PositionOrigin.LEGACY_OPENING_BALANCE,
            strategy_book=None,
        ),
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


def portfolio_snapshot(
    as_of_time: datetime = datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
) -> PortfolioSnapshot:
    lot = PortfolioLot(
        lot_id="lot-1",
        security_id="000001.SZ",
        quantity=500,
        available_to_sell=400,
        average_cost=Decimal("10.20"),
        effective_at=datetime(2026, 7, 16, 7, 0, tzinfo=UTC),
        origin=PositionOrigin.RECORDED_TRADE,
        strategy_book=StrategyBook.CORE,
        entry_score=Decimal("60"),
        initial_risk_per_share=Decimal("1"),
        effective_stop=Decimal("9.50"),
        highest_close=Decimal("11"),
        add_count=0,
        buy_date=date(2026, 7, 16),
    )
    return PortfolioSnapshot(
        portfolio_id="default",
        as_of_time=as_of_time,
        version=7,
        cash=Decimal("350000"),
        equity=Decimal("1000000"),
        lots=(lot,),
    )


def point_in_time_snapshot(
    as_of_time: datetime = datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
    *,
    issues: tuple[QualityIssue, ...] = (),
) -> PointInTimeSnapshot:
    return PointInTimeSnapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope.holding_analysis(("000001.SZ",)),
        data_grade=DataGrade.RESEARCH,
        market_inputs=(),
        security_observations=(),
        quality=SnapshotQuality(issues),
        lineage=(),
        manifest_hash="manifest-sha256-abc123",
    )


def security_evaluation(
    *,
    hard_stop: bool = False,
    llm_factor_valid: bool = True,
) -> SecurityEvaluation:
    factors = FactorScores(70.0, 65.0, 60.0, 55.0, 50.0, 62.5, 0.8) if llm_factor_valid else None
    return SecurityEvaluation(
        security_id="000001.SZ",
        name="平安银行",
        industry="bank",
        theme=None,
        factors=factors,
        market_state=MarketState.NEUTRAL,
        hard_filter_passed=llm_factor_valid,
        policy_sources_available=True,
        llm_factor_valid=llm_factor_valid,
        financial_light=FinancialLight.GREEN,
        policy_direction="supportive",
        breakout_confirmed=False,
        pullback_confirmed=False,
        strengthened_confirmed=False,
        days_since_breakout=0,
        held=True,
        close=10.80,
        ma20=10.50,
        ma60=10.00,
        atr14=0.50,
        r_multiple=1.50,
        rank_percentile=0.80,
        red_light=False,
        hard_stop=hard_stop,
        market_reduction=False,
        book_exit=False,
        rank_exit=False,
        stop_raise_required=False,
        sizing=None,
        constraint=ConstraintDecision(True, ()),
        quality_codes=() if llm_factor_valid else ("LLM_FACTOR_INVALID",),
        reasons=(ReasonCode.ELIGIBLE,),
    )


def strategy_evaluation(
    as_of_time: datetime = datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
    *,
    securities: tuple[SecurityEvaluation, ...] | None = None,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        as_of_time=as_of_time,
        strategy_version="v2.12",
        manifest_hash="manifest-sha256-abc123",
        market=MarketRegimeDecision(
            state=MarketState.NEUTRAL,
            max_exposure=0.6,
            allow_new_risk=False,
            allow_swing=False,
            confidence="medium",
            week_cooldown_remaining=0,
            month_cooldown_remaining=0,
        ),
        portfolio_summary=PortfolioView(
            net_equity=1_000_000,
            gross_exposure=0.65,
            portfolio_risk=0.0125,
            position_count=1,
        ),
        securities=securities or (security_evaluation(),),
    )
