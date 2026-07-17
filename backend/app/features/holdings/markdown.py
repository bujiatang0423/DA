from backend.app.contracts.grades import DataGrade

from .models import HoldingAnalysisResult


_DATA_GRADE_DESCRIPTIONS: dict[DataGrade, str] = {
    DataGrade.RESEARCH: "研究级数据",
    DataGrade.PIT_VERIFIED: "PIT 数据已验证",
}


def _format_codes(codes: tuple[str, ...]) -> str:
    if not codes:
        return "无"
    return ", ".join(f"`{code}`" for code in codes)


def _format_optional(value: object | None) -> str:
    return "无" if value is None else str(value)


def render_markdown(result: HoldingAnalysisResult) -> str:
    data_grade_description = _DATA_GRADE_DESCRIPTIONS[result.data_grade]
    lines = [
        "---",
        f"run_id: {result.run_id}",
        f"portfolio_id: {result.portfolio_id}",
        f"as_of_time: {result.as_of_time.isoformat()}",
        f"strategy_version: {result.strategy_version}",
        f"manifest_hash: {result.manifest_hash}",
        f"data_grade: {result.data_grade.value}",
        f"llm_grade: {result.llm_grade.value}",
        "auto_trade_enabled: false",
        "human_confirm_required: true",
        "---",
        "",
        "# 持仓分析",
        "",
        "> 仅供人工确认，不自动下单。",
        "",
        "## 组合概览",
        "",
        f"- 组合 ID：`{result.portfolio_id}`",
        f"- 分析时间：{result.as_of_time.isoformat()}",
        f"- 输入 manifest：`{result.manifest_hash}`",
        f"- 数据等级：{data_grade_description}（`{result.data_grade.value}`）",
        f"- LLM 数据等级：`{result.llm_grade.value}`",
        f"- 市场状态：{result.summary.market_state}",
        f"- 组合权益：{result.summary.equity}",
        f"- 现金：{result.summary.cash}",
        f"- 总敞口：{result.summary.gross_exposure_pct}%",
        f"- 组合风险：{result.summary.portfolio_risk_pct}%",
        "",
        "## 持仓明细",
        "",
    ]
    for item in result.items:
        strategy_book = f"`{item.strategy_book.value}`" if item.strategy_book else "未追认"
        pending_action = item.pending_target_action.value if item.pending_target_action else None
        factors = item.factors
        item_lines = [
            f"### {item.security_id} {item.security_name}",
            "",
            f"- 证券 ID：`{item.security_id}`",
            f"- 证券名称：{item.security_name}",
            f"- 来源：`{item.origin.value}`",
            f"- 策略账本：{strategy_book}",
            f"- 持仓数量：{item.quantity}",
            f"- 可卖数量：{item.available_to_sell}",
            f"- 平均成本：{item.average_cost}",
            f"- 收盘价：{item.close}",
            f"- 市场状态：{item.market_state}",
            f"- 建议动作：`{item.advised_action.value}`",
            f"- 规则计划数量：{item.planned_quantity}",
            f"- 待执行目标动作：{_format_optional(pending_action)}",
            (
                f"- 因子：P={factors.p} / F={factors.f} / R={factors.r} / "
                f"T={factors.t} / V={factors.v} / S={factors.s}"
            ),
            f"- 百分位排名：{factors.percentile_rank}",
            f"- R 倍数：{_format_optional(item.r_multiple)}",
            f"- 有效止损：{_format_optional(item.effective_stop)}",
            f"- 建议新止损：{_format_optional(item.proposed_effective_stop)}",
            f"- 原因码：{_format_codes(tuple(code.value for code in item.reason_codes))}",
        ]
        if item.quality_codes:
            item_lines.append(f"- 质量码：{_format_codes(item.quality_codes)}")
        if item.evidence_refs:
            item_lines.append(f"- 证据引用：{_format_codes(item.evidence_refs)}")
        lines.extend((*item_lines, ""))
    return "\n".join(lines) + "\n"
