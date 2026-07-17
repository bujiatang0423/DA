from .models import HoldingAnalysisResult


def render_markdown(result: HoldingAnalysisResult) -> str:
    lines = [
        "---",
        f"run_id: {result.run_id}",
        f"portfolio_id: {result.portfolio_id}",
        f"as_of_time: {result.as_of_time.isoformat()}",
        f"strategy_version: {result.strategy_version}",
        f"data_grade: {result.data_grade.value}",
        f"llm_grade: {result.llm_grade.value}",
        "auto_trade_enabled: false",
        "human_confirm_required: true",
        "---",
        "",
        "# 持仓分析建议",
        "",
    ]
    for item in result.items:
        lines.extend(
            [
                f"## {item.security_id} {item.security_name}",
                f"- 建议动作：`{item.advised_action.value}`",
                f"- 建议数量：{item.planned_quantity}",
                f"- 当前价格：{item.close}",
                f"- 原因：{', '.join(code.value for code in item.reason_codes) or '无'}",
                "",
            ]
        )
    return "\n".join(lines)
