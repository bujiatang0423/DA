from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.app.features.candidates.models import CandidateRecommendationResult
from backend.app.features.candidates.service import (
    CandidateRecommendationCommand,
    CandidateService,
)
from backend.app.core.market.pit_models import QualityIssue, QualitySeverity
from backend.tests.features.holdings.factories import (
    point_in_time_snapshot,
    portfolio_snapshot,
    strategy_evaluation,
)


@dataclass
class FrozenWarehouse:
    snapshot_value: object

    def snapshot(self, *, as_of_time: datetime, scope: object) -> object:
        del scope
        assert as_of_time == self.snapshot_value.as_of_time  # type: ignore[union-attr]
        return self.snapshot_value


@dataclass
class FrozenPortfolioReader:
    snapshot_value: object

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> object:
        assert portfolio_id == "default"
        assert as_of_time == self.snapshot_value.as_of_time  # type: ignore[union-attr]
        return self.snapshot_value


@dataclass
class FrozenInputBuilder:
    prepared: object = field(default_factory=object)

    def build(self, *, snapshot: object, portfolio: object, strategy_version: str) -> object:
        del snapshot, portfolio
        assert strategy_version == "v2.12"
        return self.prepared


@dataclass
class FrozenStrategy:
    evaluation: object

    def evaluate(self, prepared: object) -> object:
        assert prepared is not None
        return self.evaluation


@dataclass
class RecordingRepository:
    saved: list[CandidateRecommendationResult] = field(default_factory=list)

    def save(self, result: CandidateRecommendationResult) -> None:
        self.saved.append(result)


def test_candidate_results_are_manual_only_and_feature_does_not_parse_advice_text() -> None:
    fields = CandidateRecommendationResult.__dataclass_fields__
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("backend/app/features/candidates").glob("*.py")
    )

    assert fields["auto_trade_enabled"].default is False
    assert fields["human_confirm_required"].default is True
    assert "parse_markdown" not in source
    la_workspace = "/Users/bujiatang/workspace/" + "LA"
    assert la_workspace not in source
    assert "llm_raw_output.action" not in source


def test_same_manifest_and_state_project_identical_items_for_different_run_ids() -> None:
    as_of_time = datetime(2026, 7, 20, 7, 0, tzinfo=UTC)
    snapshot = point_in_time_snapshot(as_of_time)
    repository = RecordingRepository()
    service = CandidateService(
        FrozenWarehouse(snapshot),  # type: ignore[arg-type]
        FrozenPortfolioReader(portfolio_snapshot(as_of_time)),  # type: ignore[arg-type]
        FrozenInputBuilder(),  # type: ignore[arg-type]
        FrozenStrategy(strategy_evaluation(as_of_time)),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
    )

    first = service.run(CandidateRecommendationCommand("run-a", "default", as_of_time))
    second = service.run(CandidateRecommendationCommand("run-b", "default", as_of_time))

    assert first.manifest_hash == second.manifest_hash
    assert first.items == second.items


def test_quality_error_fails_closed_without_evaluating_candidate_strategy() -> None:
    as_of_time = datetime(2026, 7, 20, 7, 0, tzinfo=UTC)
    snapshot = point_in_time_snapshot(
        as_of_time,
        issues=(
            QualityIssue(
                code="FROZEN_DATA_MISSING",
                severity=QualitySeverity.ERROR,
                dataset="daily_bars",
                entity_id=None,
                detail="fixture only",
            ),
        ),
    )

    @dataclass
    class InputBuilderThatMustNotRun:
        def build(self, **_: object) -> object:
            raise AssertionError("candidate strategy inputs must not be built for invalid PIT data")

    @dataclass
    class StrategyThatMustNotRun:
        def evaluate(self, _: object) -> object:
            raise AssertionError("candidate strategy must not run for invalid PIT data")

    repository = RecordingRepository()
    result = CandidateService(
        FrozenWarehouse(snapshot),  # type: ignore[arg-type]
        FrozenPortfolioReader(portfolio_snapshot(as_of_time)),  # type: ignore[arg-type]
        InputBuilderThatMustNotRun(),  # type: ignore[arg-type]
        StrategyThatMustNotRun(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
    ).run(CandidateRecommendationCommand("quality-error", "default", as_of_time))

    assert result.items == ()
    assert result.market_state == "weak"
    assert result.quality_codes == ("FROZEN_DATA_MISSING", "LLM_EVIDENCE_MISSING")
    assert repository.saved == [result]
