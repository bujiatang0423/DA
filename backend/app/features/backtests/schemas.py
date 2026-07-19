from __future__ import annotations

from datetime import datetime

from backend.app.contracts.common import ContractModel
from backend.app.contracts.runs import Page
from backend.app.features.backtests.models import BacktestGroupSummary, StrategyGroup


class BacktestResultResponse(ContractModel):
    run_id: str
    status: str
    strategy_version: str
    input_manifest_hash: str
    created_at: datetime
    groups: tuple[BacktestGroupSummary, ...]
    group: StrategyGroup
    metrics: dict[str, str | int | None]
    metric_details: dict[str, object]
    warnings: list[str]
    equity_curve: Page[dict[str, str]]
    trades: Page[dict[str, str]]
    rejected_attempts: Page[dict[str, str]]
