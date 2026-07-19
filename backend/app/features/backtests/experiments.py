from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

from backend.app.contracts.grades import LlmGrade
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestRequest,
    StrategyGroup,
)


FACTOR_MASKS: dict[StrategyGroup, frozenset[str]] = {
    StrategyGroup.A: frozenset({"R", "T", "V"}),
    StrategyGroup.B: frozenset({"F", "R", "T", "V"}),
    StrategyGroup.C: frozenset({"P", "R", "T", "V"}),
    StrategyGroup.D: frozenset({"P", "F", "R", "T", "V"}),
}


class BacktestGroupRunner(Protocol):
    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade,
    ) -> BacktestGroupResult: ...


def llm_grade_for(group: StrategyGroup) -> LlmGrade:
    return LlmGrade.NOT_USED if group is StrategyGroup.A else LlmGrade.RECONSTRUCTED


def combine_group_results(
    request: BacktestRequest,
    results: Sequence[BacktestGroupResult],
) -> BacktestExperimentResult:
    ordered_results = tuple(sorted(results, key=lambda result: result.group.value))
    manifest_input = "|".join(result.input_manifest_hash for result in ordered_results)
    return BacktestExperimentResult(
        request=request,
        input_manifest_hash=hashlib.sha256(manifest_input.encode("utf-8")).hexdigest(),
        groups=ordered_results,
        warnings=sorted({warning for result in ordered_results for warning in result.warnings}),
    )


def compare_metrics(
    results: Sequence[BacktestGroupResult],
) -> dict[str, dict[StrategyGroup, str | int | None]]:
    comparison: dict[str, dict[StrategyGroup, str | int | None]] = {}
    for result in sorted(results, key=lambda item: item.group.value):
        for metric, value in result.metrics.items():
            comparison.setdefault(metric, {})[result.group] = value
    return {metric: comparison[metric] for metric in sorted(comparison)}


class ExperimentRunner:
    def __init__(self, engine: BacktestGroupRunner) -> None:
        self._engine = engine

    def run(self, request: BacktestRequest) -> BacktestExperimentResult:
        results = tuple(
            self._engine.run(
                request.with_group(group),
                group,
                llm_grade_for(group),
            )
            for group in request.groups
        )
        return combine_group_results(request, results)
