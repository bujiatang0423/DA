from datetime import date

from backend.app.contracts.grades import DataGrade, LlmGrade
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
        warnings=[f"warning-{group.value}", "research_only"],
    )


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[BacktestRequest, StrategyGroup, LlmGrade]] = []
        self.initial_candidate_states: list[dict[str, str]] = []

    def run(
        self,
        request: BacktestRequest,
        group: StrategyGroup,
        llm_grade: LlmGrade,
    ) -> BacktestGroupResult:
        candidate_state: dict[str, str] = {}
        self.initial_candidate_states.append(dict(candidate_state))
        candidate_state["only-this-group"] = group.value
        self.calls.append((request, group, llm_grade))
        return _group_result(group, llm_grade)


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
    assert [group.group for group in result.groups] == request.groups
    assert result.warnings == [
        "research_only",
        "warning-A",
        "warning-B",
        "warning-C",
        "warning-D",
    ]


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
