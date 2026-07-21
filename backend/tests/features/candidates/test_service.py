from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    PointInTimeSnapshot,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.features.candidates.service import (
    CandidateRecommendationCommand,
    CandidateService,
)
from backend.tests.features.holdings.factories import (
    portfolio_snapshot,
    security_evaluation,
    strategy_evaluation,
)


@dataclass
class FakeWarehouse:
    value: PointInTimeSnapshot

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        assert as_of_time == self.value.as_of_time
        assert scope == SnapshotScope.candidate_recommendation()
        return self.value


@dataclass
class FakePortfolios:
    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> object:
        assert portfolio_id == "default"
        return portfolio_snapshot(as_of_time)


@dataclass
class FakeInputBuilder:
    def build(self, *, snapshot: object, portfolio: object, strategy_version: str) -> object:
        assert strategy_version == "v2.12"
        return object()


@dataclass
class FakeStrategy:
    value: object

    def evaluate(self, prepared: object) -> object:
        return self.value


@dataclass
class FakeRepository:
    saved: list[object] = field(default_factory=list)

    def save(self, result: object) -> None:
        self.saved.append(result)


def test_service_projects_only_visible_lineage_backed_evidence() -> None:
    as_of_time = datetime(2026, 7, 20, 7, 0, tzinfo=UTC)
    source_hash = "a" * 64
    records = (
        TemporalRecord(
            record_id="daily-bar-1",
            kind=DataKind.DAILY_BAR_RAW,
            entity_id="000001.SZ",
            event_time=as_of_time,
            observed_at=as_of_time,
            available_at=as_of_time,
            source_artifact_hash=source_hash,
            payload={},
        ),
        TemporalRecord(
            record_id="llm-factor-1",
            kind=DataKind.LLM_FACTOR,
            entity_id="000001.SZ",
            event_time=as_of_time,
            observed_at=as_of_time,
            available_at=as_of_time,
            source_artifact_hash=source_hash,
            payload={"grade": "forward_observed", "valid": True},
        ),
    )
    snapshot = PointInTimeSnapshot(
        as_of_time=as_of_time,
        scope=SnapshotScope.candidate_recommendation(),
        data_grade=DataGrade.RESEARCH,
        market_inputs=(),
        security_observations=(SecurityObservation("000001.SZ", records),),
        quality=SnapshotQuality(()),
        lineage=(LineageRef("batch-1", "pit", source_hash),),
        manifest_hash="manifest",
    )
    warehouse = FakeWarehouse(snapshot)
    repository = FakeRepository()
    service = CandidateService(
        warehouse,
        FakePortfolios(),
        FakeInputBuilder(),
        FakeStrategy(strategy_evaluation(as_of_time, securities=(security_evaluation(),))),
        repository,
    )

    result = service.run(CandidateRecommendationCommand("candidate-run", "default", as_of_time))

    assert result.llm_grade.value == "forward_observed"
    assert result.items[0].evidence_refs == (
        f"pit:daily_bar_raw:{source_hash}",
        f"pit:llm_factor:{source_hash}",
    )
    assert repository.saved == [result]
