import importlib
import inspect
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotQuality, SnapshotScope
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.features.backtests import models
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestRequest,
    BacktestRunSummary,
    OrderIntent,
    OrderSide,
    StrategyGroup,
)
from backend.app.features.backtests.ports import BacktestDecisionContext, BacktestRepository


def request_payload() -> dict[str, object]:
    return {
        "strategy_version": "v2.12",
        "start_date": date(2020, 1, 2),
        "end_date": date(2023, 12, 29),
        "initial_cash": Decimal("150000"),
        "groups": [
            StrategyGroup.A,
            StrategyGroup.B,
            StrategyGroup.C,
            StrategyGroup.D,
        ],
    }


def make_request() -> BacktestRequest:
    return BacktestRequest.model_validate(request_payload())


def make_result() -> BacktestExperimentResult:
    group_result = BacktestGroupResult(
        group=StrategyGroup.A,
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.NOT_USED,
        input_manifest_hash="manifest",
        equity_curve=[{"trade_date": "2024-01-02", "equity": "150000"}],
        trades=[],
        metrics={"observations": 1},
        warnings=["research_only"],
    )
    return BacktestExperimentResult(
        request=make_request(),
        input_manifest_hash="manifest",
        groups=(group_result,),
        warnings=["research_only"],
    )


def make_context() -> BacktestDecisionContext:
    as_of_time = datetime(2024, 1, 2, 15, 30)
    snapshot = PointInTimeSnapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope(),
        data_grade=DataGrade.RESEARCH,
        market_inputs=(),
        security_observations=(),
        quality=SnapshotQuality(()),
        lineage=(),
        manifest_hash="manifest",
    )
    portfolio = PortfolioSnapshot(
        portfolio_id="backtest",
        as_of_time=as_of_time,
        version=0,
        cash=Decimal("150000"),
        equity=Decimal("150000"),
        lots=(),
    )
    return BacktestDecisionContext(
        as_of_time=as_of_time,
        next_trade_date=date(2024, 1, 3),
        strategy_version="v2.12",
        group=StrategyGroup.A,
        snapshot=snapshot,
        portfolio=portfolio,
        candidate_states={"600000.SH": "eligible"},
    )


def intent_payload() -> dict[str, object]:
    return {
        "order_id": "order-1",
        "security_id": "600000.SH",
        "side": OrderSide.BUY,
        "quantity": 100,
        "signal_date": date(2024, 1, 2),
        "earliest_trade_date": date(2024, 1, 3),
        "strategy_book": "core",
        "priority": 100,
        "signal_close": Decimal("10.00"),
    }


@pytest.mark.parametrize(
    ("field_name", "grade"),
    [
        ("data_grade", DataGrade.RESEARCH),
        ("llm_grade", LlmGrade.RECONSTRUCTED),
    ],
)
def test_request_does_not_accept_result_grades(field_name: str, grade: object) -> None:
    request = make_request()

    assert "data_grade" not in request.model_dump()
    assert "llm_grade" not in request.model_dump()
    with pytest.raises(ValidationError):
        BacktestRequest.model_validate({**request.model_dump(), field_name: grade})


def test_request_derivation_returns_new_validated_requests() -> None:
    request = make_request()

    period = request.with_period(date(2021, 1, 4), date(2021, 12, 31))
    group = request.with_group(StrategyGroup.C)

    assert period is not request
    assert (period.start_date, period.end_date) == (date(2021, 1, 4), date(2021, 12, 31))
    assert group is not request
    assert group.groups == [StrategyGroup.C]
    assert request.groups == list(StrategyGroup)


def test_request_rejects_inverted_dates() -> None:
    with pytest.raises(ValidationError):
        BacktestRequest.model_validate(
            {
                **request_payload(),
                "start_date": date(2024, 2, 1),
                "end_date": date(2024, 1, 1),
            }
        )


def test_request_requires_out_of_sample_boundary_after_backtest_start() -> None:
    with pytest.raises(ValidationError, match="out_of_sample_start"):
        BacktestRequest.model_validate(
            {
                **request_payload(),
                "out_of_sample_start": date(2020, 1, 2),
            }
        )


def test_request_is_frozen_and_uses_research_fee_schedule() -> None:
    request = make_request()

    assert request.fee_schedule_version == "research-cn-a-2023-08-28"
    with pytest.raises(ValidationError):
        request.initial_cash = Decimal("1")


@pytest.mark.parametrize(
    "overrides",
    [
        {"initial_cash": Decimal("0")},
        {"groups": []},
        {"buy_slippage_bps": -1},
        {"sell_slippage_bps": -1},
    ],
)
def test_request_rejects_invalid_boundaries(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BacktestRequest.model_validate({**request_payload(), **overrides})


def test_order_intent_has_research_execution_defaults() -> None:
    intent = OrderIntent.model_validate(intent_payload())

    assert intent.max_participation_rate == Decimal("0.002")
    assert intent.stop_price is None
    assert intent.reason_codes == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": 0},
        {"priority": 0},
        {"signal_close": Decimal("0")},
        {"stop_price": Decimal("0")},
        {"max_participation_rate": Decimal("0")},
        {"max_participation_rate": Decimal("1.001")},
    ],
)
def test_order_intent_rejects_invalid_boundaries(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OrderIntent.model_validate({**intent_payload(), **overrides})


def test_result_grades_are_structured_on_group_summaries() -> None:
    summary_type = getattr(models, "BacktestGroupSummary", None)

    assert summary_type is not None, "BacktestGroupSummary contract is missing"
    group_summary = summary_type(
        group=StrategyGroup.A,
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.NOT_USED,
        input_manifest_hash="manifest",
        metrics={"observations": 1},
    )
    run_summary = BacktestRunSummary(
        run_id="run-1",
        status="succeeded",
        strategy_version="v2.12",
        input_manifest_hash="manifest",
        groups=(group_summary,),
        created_at=datetime(2024, 1, 2),
    )

    assert run_summary.groups == (group_summary,)


def test_experiment_result_preserves_group_result_details() -> None:
    result = make_result()

    assert result.groups[0].data_grade is DataGrade.RESEARCH
    assert result.groups[0].llm_grade is LlmGrade.NOT_USED


def test_repository_publishes_a_result_with_run_and_artifact_context() -> None:
    parameters = tuple(inspect.signature(BacktestRepository.publish_result).parameters)

    assert parameters == ("self", "run_id", "result", "artifacts")


def test_backtest_fakes_follow_decision_repository_and_artifact_contracts() -> None:
    try:
        fakes = importlib.import_module("backend.tests.features.backtests.fakes")
    except ModuleNotFoundError:
        pytest.fail("backtest test fakes are missing")

    context = make_context()
    intent = OrderIntent.model_validate(intent_payload())
    decision = fakes.FixedDecisionPort((intent,)).decide(context)
    assert decision.intents == (intent,)
    assert decision.candidate_states is context.candidate_states

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    result = make_result()
    artifacts = fakes.MemoryArtifactRepository()
    repository = fakes.MemoryBacktestRepository()
    repository.publish_result(run_id, result, artifacts)
    assert repository.results[run_id] is result

    ref = artifacts.save_json(object(), run_id, "result.json", {"status": "succeeded"})
    with artifacts.open(run_id, ref.artifact_id) as stream:
        assert json.load(stream) == {"status": "succeeded"}
    with pytest.raises(KeyError):
        artifacts.open(UUID(int=2), ref.artifact_id)
