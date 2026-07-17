from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.portfolio.models import PositionOrigin, StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode
from backend.app.features.holdings.markdown import render_markdown
from backend.app.features.holdings.models import (
    AdviceAction,
    HoldingAdviceItem,
    HoldingAnalysisResult,
    HoldingFactors,
    HoldingRiskSummary,
)


@pytest.fixture
def analysis_result() -> HoldingAnalysisResult:
    return HoldingAnalysisResult(
        run_id="holding-run-1",
        portfolio_id="portfolio-alpha",
        as_of_time=datetime(2026, 7, 17, 14, 50, tzinfo=timezone(timedelta(hours=8))),
        strategy_version="v2.12",
        manifest_hash="manifest-sha256-abc123",
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.NOT_USED,
        summary=HoldingRiskSummary(
            equity=Decimal("1000000"),
            cash=Decimal("350000"),
            gross_exposure_pct=Decimal("65.00"),
            portfolio_risk_pct=Decimal("1.25"),
            market_state="neutral",
        ),
        items=(
            HoldingAdviceItem(
                security_id="600000.SH",
                security_name="浦发银行",
                origin=PositionOrigin.LEGACY_OPENING_BALANCE,
                strategy_book=None,
                quantity=1000,
                available_to_sell=800,
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
                reason_codes=(ReasonCode.ELIGIBLE, ReasonCode.MARKET_WEAK),
                quality_codes=("PRICE_PIT_VERIFIED",),
                evidence_refs=("market-close:600000.SH:2026-07-17",),
            ),
            HoldingAdviceItem(
                security_id="000001.SZ",
                security_name="平安银行",
                origin=PositionOrigin.RECORDED_TRADE,
                strategy_book=StrategyBook.CORE,
                quantity=500,
                available_to_sell=500,
                average_cost=Decimal("11.00"),
                close=Decimal("10.50"),
                market_state="neutral",
                factors=HoldingFactors(
                    p=Decimal("50"),
                    f=Decimal("52"),
                    r=Decimal("48"),
                    t=Decimal("45"),
                    v=Decimal("40"),
                    s=Decimal("47"),
                    percentile_rank=Decimal("0.40"),
                ),
                r_multiple=None,
                effective_stop=None,
                proposed_effective_stop=None,
                advised_action=AdviceAction.HOLD,
                planned_quantity=0,
                pending_target_action=None,
                reason_codes=(),
                quality_codes=(),
                evidence_refs=(),
            ),
        ),
    )


def test_render_markdown_includes_structured_analysis(
    analysis_result: HoldingAnalysisResult,
) -> None:
    markdown = render_markdown(analysis_result)

    assert "# 持仓分析" in markdown
    assert "仅供人工确认，不自动下单" in markdown
    assert "auto_trade_enabled: false" in markdown
    assert "human_confirm_required: true" in markdown
    assert "研究级数据" in markdown
    assert "portfolio-alpha" in markdown
    assert "2026-07-17T14:50:00+08:00" in markdown
    assert analysis_result.manifest_hash in markdown
    assert "市场状态：neutral" in markdown
    assert "总敞口：65.00%" in markdown
    assert "组合风险：1.25%" in markdown
    assert "600000.SH 浦发银行" in markdown
    assert "来源：`legacy_opening_balance`" in markdown
    assert "策略账本：未追认" in markdown
    assert "建议动作：`raise_stop`" in markdown
    assert "规则计划数量：0" in markdown
    assert "可卖数量：800" in markdown
    assert "P=70 / F=65 / R=60 / T=55 / V=50 / S=62.5" in markdown
    assert "有效止损：9.50" in markdown
    assert "建议新止损：9.80" in markdown
    assert "原因码：`ELIGIBLE`, `MARKET_WEAK`" in markdown
    assert "质量码：`PRICE_PIT_VERIFIED`" in markdown
    assert "证据引用：`market-close:600000.SH:2026-07-17`" in markdown
    assert "策略账本：`core`" in markdown


def test_render_markdown_describes_pit_verified_data(
    analysis_result: HoldingAnalysisResult,
) -> None:
    result = replace(analysis_result, data_grade=DataGrade.PIT_VERIFIED)

    markdown = render_markdown(result)

    assert "数据等级：PIT 数据已验证（`pit_verified`）" in markdown
