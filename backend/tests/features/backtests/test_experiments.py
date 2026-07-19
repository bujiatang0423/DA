from datetime import date, datetime

import pytest

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotQuality
from backend.app.features.backtests.engine import BacktestEngine
from backend.app.features.backtests.experiments import (
    FACTOR_MASKS,
    ExperimentRunner,
    compare_metrics,
    llm_grade_for,
)
from backend.app.features.backtests.models import (
    BacktestGroupResult,
    BacktestRequest,
    StrategyGroup,
)
from backend.app.features.backtests.ports import BacktestDecision, BacktestDecisionContext


EXPECTED_MASKS: dict[StrategyGroup, frozenset[str]] = {
    StrategyGroup.A: frozenset({"R", "T", "V"}),
    StrategyGroup.B: frozenset({"F", "R", "T", "V"}),
    StrategyGroup.C: frozenset({"P", "R", "T", "V"}),
    StrategyGroup.D: frozenset({"P", "F", "R", "T", "V"}),
}


def _request() -> BacktestRequest:
    return BacktestRequest(
        strategy_version="v2.12",
        start_date=date(2021, 1, 4),
        end_date=date(2023, 12, 29),
        initial_cash="150000",
        groups=[StrategyGroup.A, StrategyGroup.B, StrategyGroup.C, StrategyGroup.D],
    )


def _group_result(group: StrategyGroup, grade: LlmGrade) -> BacktestGroupResult:
    return BacktestGroupResult(
        group=group,
        data_grade=DataGrade.RESEARCH,
        llm_grade=grade,
        input_manifest_hash=f"manifest-{group.value}",
        equity_curve=[],
        trades=[],
        metrics={"annualized_return": group.value, "turnover": 4},
        comparison_inputs=_comparison_inputs(),
        warnings=[f"warning-{group.value}", "research_only"],
    )


def _comparison_inputs(*, snapshot_manifest: str = "pit-manifest") -> dict[str, str]:
    return {
        "pit_input_manifest_hash": snapshot_manifest,
        "universe_hash": "universe-hash",
        "market_filter_hash": "market-filter-hash",
        "execution_settings_hash": "execution-settings-hash",
        "fee_schedule_version": "research-cn-a-2023-08-28",
        "risk_budget": "not_configured",
        "start_date": "2021-01-04",
        "end_date": "2023-12-29",
    }


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[BacktestRequest, StrategyGroup, LlmGrade]] = []
        self.initial_candidate_states: list[dict[str, str]] = []

    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade,
        *,
        factor_mask: frozenset[str],
    ) -> BacktestGroupResult:
        candidate_state: dict[str, str] = {}
        self.initial_candidate_states.append(dict(candidate_state))
        candidate_state["only-this-group"] = group.value
        self.calls.append((request, group, llm_grade))
        result = _group_result(group, llm_grade)
        return result.model_copy(
            update={"metrics": {**result.metrics, "p_enabled": int("P" in factor_mask)}}
        )


def test_factor_masks_differ_only_by_selected_factor() -> None:
    assert FACTOR_MASKS == EXPECTED_MASKS
    assert set.intersection(*(set(mask) for mask in FACTOR_MASKS.values())) == {"R", "T", "V"}


def test_only_group_a_avoids_reconstructed_llm_output() -> None:
    assert llm_grade_for(StrategyGroup.A) is LlmGrade.NOT_USED
    assert all(
        llm_grade_for(group) is LlmGrade.RECONSTRUCTED
        for group in (StrategyGroup.B, StrategyGroup.C, StrategyGroup.D)
    )


def test_runner_isolates_groups_without_changing_base_inputs() -> None:
    engine = RecordingEngine()
    request = _request()

    result = ExperimentRunner(engine).run(request)

    assert [call[1] for call in engine.calls] == request.groups
    assert engine.initial_candidate_states == [{}, {}, {}, {}]
    assert [call[0].groups for call in engine.calls] == [[group] for group in request.groups]
    base_inputs = [
        (
            call[0].start_date,
            call[0].end_date,
            call[0].initial_cash,
            call[0].buy_slippage_bps,
            call[0].sell_slippage_bps,
            call[0].fee_schedule_version,
        )
        for call in engine.calls
    ]
    assert base_inputs == [base_inputs[0]] * 4
    assert [call[2] for call in engine.calls] == [
        LlmGrade.NOT_USED,
        LlmGrade.RECONSTRUCTED,
        LlmGrade.RECONSTRUCTED,
        LlmGrade.RECONSTRUCTED,
    ]
    assert [group.metrics["p_enabled"] for group in result.groups] == [0, 0, 1, 1]
    assert [group.group for group in result.groups] == request.groups
    assert result.warnings == [
        "research_only",
        "warning-A",
        "warning-B",
        "warning-C",
        "warning-D",
    ]


def test_factor_mask_reaches_real_engine_decision_context() -> None:
    observed_masks: dict[StrategyGroup, frozenset[str]] = {}
    decision_outputs: dict[StrategyGroup, str] = {}

    class TradingDays:
        def between(self, start_date: date, end_date: date) -> tuple[date, ...]:
            return (date(2021, 1, 4), date(2021, 1, 5))

    class Warehouse:
        def snapshot(self, *, as_of_time: datetime, scope: object) -> PointInTimeSnapshot:
            return PointInTimeSnapshot(
                as_of_time,
                scope,
                DataGrade.RESEARCH,
                (),
                (),
                SnapshotQuality(()),
                (),
                "pit-manifest",
            )

    class Decisions:
        def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
            observed_masks[context.group] = context.factor_mask
            p_enabled = str("P" in context.factor_mask)
            decision_outputs[context.group] = p_enabled
            return BacktestDecision((), {"p_enabled": p_enabled})

    request = _request().with_period(date(2021, 1, 4), date(2021, 1, 5))
    result = ExperimentRunner(BacktestEngine(TradingDays(), Warehouse(), Decisions())).run(request)

    assert observed_masks == FACTOR_MASKS
    assert decision_outputs == {
        StrategyGroup.A: "False",
        StrategyGroup.B: "False",
        StrategyGroup.C: "True",
        StrategyGroup.D: "True",
    }
    assert {tuple(group.comparison_inputs.items()) for group in result.groups} == {
        tuple(result.groups[0].comparison_inputs.items())
    }


def test_runner_rejects_non_factor_input_mismatch() -> None:
    class MismatchedEngine(RecordingEngine):
        def run(
            self,
            request: BacktestRequest,
            group: StrategyGroup,
            llm_grade: LlmGrade,
            *,
            factor_mask: frozenset[str],
        ) -> BacktestGroupResult:
            result = super().run(request, group, llm_grade, factor_mask=factor_mask)
            if group is StrategyGroup.B:
                return result.model_copy(
                    update={"comparison_inputs": _comparison_inputs(snapshot_manifest="other-pit")}
                )
            return result

    request = _request().model_copy(update={"groups": [StrategyGroup.A, StrategyGroup.B]})

    with pytest.raises(ValueError, match="non-factor comparison input differs"):
        ExperimentRunner(MismatchedEngine()).run(request)


def test_metric_comparison_is_explicit_and_deterministic() -> None:
    results = tuple(
        _group_result(group, llm_grade_for(group))
        for group in (StrategyGroup.D, StrategyGroup.A, StrategyGroup.C, StrategyGroup.B)
    )

    comparison = compare_metrics(results)

    assert comparison == {
        "annualized_return": {
            StrategyGroup.A: "A",
            StrategyGroup.B: "B",
            StrategyGroup.C: "C",
            StrategyGroup.D: "D",
        },
        "turnover": {
            StrategyGroup.A: 4,
            StrategyGroup.B: 4,
            StrategyGroup.C: 4,
            StrategyGroup.D: 4,
        },
    }
