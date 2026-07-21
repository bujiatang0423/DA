from dataclasses import replace
from decimal import Decimal

import pytest

from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    QualityIssue,
    QualitySeverity,
    SecurityObservation,
    SnapshotScope,
    TemporalRecord,
)
from backend.app.core.market.strategy_inputs import StrategyInputError
from backend.app.core.portfolio.models import PositionOrigin
from backend.app.core.strategy.types import MarketState, StrategyPortfolioSummary
from backend.app.features.holdings.models import AdviceAction
from backend.app.features.holdings.markdown import render_markdown
from backend.app.features.holdings.service import (
    HoldingAnalysisCommand,
    HoldingAnalysisService,
    HoldingMarketDataMissing,
)
from backend.tests.features.holdings.factories import (
    point_in_time_snapshot,
    portfolio_snapshot,
    security_evaluation,
    strategy_evaluation,
)
from backend.tests.features.holdings.fakes import (
    FakeHoldingAnalysisRepository,
    FakePointInTimeWarehouse,
    FakePortfolioReader,
    FakeStrategyDecisionPort,
    FakeStrategyInputBuilder,
)


def build_service(
    *,
    snapshot_errors: tuple[QualityIssue, ...] = (),
    hard_stop: bool = False,
    llm_factor_valid: bool = True,
) -> tuple[
    HoldingAnalysisService,
    HoldingAnalysisCommand,
    FakePointInTimeWarehouse,
    FakePortfolioReader,
    FakeStrategyInputBuilder,
    FakeStrategyDecisionPort,
    FakeHoldingAnalysisRepository,
]:
    portfolio = portfolio_snapshot()
    snapshot = point_in_time_snapshot(issues=snapshot_errors)
    warehouse = FakePointInTimeWarehouse(snapshot)
    portfolios = FakePortfolioReader(portfolio)
    input_builder = FakeStrategyInputBuilder.for_context(snapshot, portfolio)
    strategy = FakeStrategyDecisionPort(
        strategy_evaluation(
            securities=(
                security_evaluation(
                    hard_stop=hard_stop,
                    llm_factor_valid=llm_factor_valid,
                ),
            )
        )
    )
    repository = FakeHoldingAnalysisRepository()
    service = HoldingAnalysisService(
        warehouse,
        portfolios,
        input_builder,
        strategy,
        repository,
    )
    command = HoldingAnalysisCommand("holding-run-service", "default", snapshot.as_of_time)
    return service, command, warehouse, portfolios, input_builder, strategy, repository


def test_service_reads_portfolio_and_market_at_identical_as_of_time() -> None:
    service, command, warehouse, portfolios, input_builder, strategy, repository = build_service()

    result = service.run(command)

    assert portfolios.requests == [(command.portfolio_id, command.as_of_time)]
    assert warehouse.requests == [
        (command.as_of_time, SnapshotScope.holding_analysis(("000001.SZ",)))
    ]
    assert input_builder.requests == [
        (warehouse.snapshot_value, portfolios.snapshot_value, "v2.12")
    ]
    assert strategy.requests == [input_builder.prepared_value]
    assert result.manifest_hash == warehouse.snapshot_value.manifest_hash
    assert result.summary.gross_exposure_pct == Decimal("65.0")
    assert repository.saved == [result]


def test_service_persists_actual_legacy_import_provenance() -> None:
    service, command, _, portfolios, _, _, _ = build_service()
    lot = replace(
        portfolios.snapshot_value.lots[0],
        origin=PositionOrigin.LEGACY_OPENING_BALANCE,
        batch_id="legacy-import-1",
        import_manifest_sha256="a" * 64,
    )
    portfolios.snapshot_value = replace(portfolios.snapshot_value, lots=(lot,))

    result = service.run(command)

    assert result.portfolio_imports[0].batch_id == "legacy-import-1"
    assert result.portfolio_imports[0].manifest_sha256 == "a" * 64


def test_service_projects_the_strategy_portfolio_summary_without_recalculation() -> None:
    service, command, _, _, _, strategy, _ = build_service()
    strategy.evaluation = replace(
        strategy.evaluation,
        portfolio_summary=StrategyPortfolioSummary(
            gross_exposure_pct=42.0,
            portfolio_risk_pct=0.9,
            market_state=MarketState.NEUTRAL,
        ),
    )

    result = service.run(command)

    assert result.summary.gross_exposure_pct == Decimal("42.0")
    assert result.summary.portfolio_risk_pct == Decimal("0.9")


def test_service_projects_only_safe_point_in_time_evidence_for_each_holding() -> None:
    service, command, warehouse, _, _, _, repository = build_service()
    artifact_hash = "a" * 64
    warehouse.snapshot_value = replace(
        warehouse.snapshot_value,
        market_inputs=(
            TemporalRecord(
                record_id="market-regime-1",
                kind=DataKind.INDEX_DAILY_BAR,
                entity_id="MARKET:CSI300",
                event_time=command.as_of_time,
                observed_at=command.as_of_time,
                available_at=command.as_of_time,
                source_artifact_hash=artifact_hash,
                payload={"untrusted_path": "/private/source.csv"},
            ),
        ),
        security_observations=(
            SecurityObservation(
                "000001.SZ",
                (
                    TemporalRecord(
                        record_id="daily-bar-1",
                        kind=DataKind.DAILY_BAR_RAW,
                        entity_id="000001.SZ",
                        event_time=command.as_of_time,
                        observed_at=command.as_of_time,
                        available_at=command.as_of_time,
                        source_artifact_hash="b" * 64,
                        payload={"raw_llm_output": "do not expose"},
                    ),
                ),
            ),
        ),
        lineage=(
            LineageRef("daily-bar-batch", "pit", ("b" * 64).upper()),
            LineageRef("market-batch", "pit", artifact_hash.upper()),
        ),
    )

    result = service.run(command)

    assert result.items[0].evidence_refs == (
        f"pit:daily_bar_raw:{'b' * 64}",
        f"pit:index_daily_bar:{artifact_hash}",
    )
    assert repository.saved == [result]


def test_service_rejects_evidence_hashes_missing_from_snapshot_lineage() -> None:
    service, command, warehouse, *_ = build_service()
    unmatched_hash = "d" * 64
    warehouse.snapshot_value = replace(
        warehouse.snapshot_value,
        security_observations=(
            SecurityObservation(
                "000001.SZ",
                (
                    TemporalRecord(
                        record_id="unmatched-record",
                        kind=DataKind.DAILY_BAR_RAW,
                        entity_id="000001.SZ",
                        event_time=command.as_of_time,
                        observed_at=command.as_of_time,
                        available_at=command.as_of_time,
                        source_artifact_hash=unmatched_hash,
                        payload={},
                    ),
                ),
            ),
        ),
        lineage=(LineageRef("other-batch", "pit", "e" * 64),),
    )

    result = service.run(command)

    assert result.items[0].evidence_refs == ()
    assert "HOLDING_EVIDENCE_UNAVAILABLE" in result.items[0].quality_codes


def test_service_never_leaks_unsafe_evidence_and_marks_it_unavailable() -> None:
    service, command, warehouse, *_ = build_service()
    unsafe_hash = "../../private/source.csv"
    warehouse.snapshot_value = replace(
        warehouse.snapshot_value,
        security_observations=(
            SecurityObservation(
                "000001.SZ",
                (
                    TemporalRecord(
                        record_id="unsafe-record-id",
                        kind=DataKind.DAILY_BAR_RAW,
                        entity_id="000001.SZ",
                        event_time=command.as_of_time,
                        observed_at=command.as_of_time,
                        available_at=command.as_of_time,
                        source_artifact_hash=unsafe_hash,
                        payload={"raw_llm_output": "do not expose"},
                    ),
                ),
            ),
        ),
    )

    result = service.run(command)

    assert result.items[0].evidence_refs == ()
    assert "HOLDING_EVIDENCE_UNAVAILABLE" in result.items[0].quality_codes
    assert unsafe_hash not in render_markdown(result)


def test_service_treats_naive_evidence_time_as_unavailable() -> None:
    service, command, warehouse, *_ = build_service()
    warehouse.snapshot_value = replace(
        warehouse.snapshot_value,
        security_observations=(
            SecurityObservation(
                "000001.SZ",
                (
                    TemporalRecord(
                        record_id="naive-time-record",
                        kind=DataKind.DAILY_BAR_RAW,
                        entity_id="000001.SZ",
                        event_time=command.as_of_time,
                        observed_at=command.as_of_time,
                        available_at=command.as_of_time.replace(tzinfo=None),
                        source_artifact_hash="c" * 64,
                        payload={},
                    ),
                ),
            ),
        ),
    )

    result = service.run(command)

    assert result.items[0].evidence_refs == ()
    assert "HOLDING_EVIDENCE_UNAVAILABLE" in result.items[0].quality_codes


def test_zero_close_from_strategy_fails_closed_without_persisting_advice() -> None:
    service, command, _, _, _, strategy, repository = build_service()
    strategy.evaluation = replace(
        strategy.evaluation,
        securities=(replace(strategy.evaluation.securities[0], close=0),),
    )

    with pytest.raises(HoldingMarketDataMissing) as exc_info:
        service.run(command)

    assert exc_info.value.code == "HOLDING_MARKET_DATA_MISSING"
    assert repository.saved == []


def test_invalid_llm_does_not_disable_an_existing_price_stop() -> None:
    service, command, *_ = build_service(hard_stop=True, llm_factor_valid=False)

    result = service.run(command)

    assert result.items[0].advised_action is AdviceAction.EXIT_ALL
    assert result.items[0].planned_quantity == 400


def test_missing_market_data_fails_closed_without_persisting_advice() -> None:
    issue = QualityIssue(
        code="REQUIRED_DATASET_MISSING",
        severity=QualitySeverity.ERROR,
        dataset=DataKind.DAILY_BAR_RAW.value,
        entity_id="000001.SZ",
        detail="daily bars are missing",
    )
    service, command, *_, repository = build_service(snapshot_errors=(issue,))

    try:
        service.run(command)
    except HoldingMarketDataMissing as exc:
        assert exc.code == "HOLDING_MARKET_DATA_MISSING"
    else:
        raise AssertionError("missing holding market data must fail closed")

    assert repository.saved == []


def test_invalid_strategy_inputs_use_stable_missing_data_error() -> None:
    service, command, *_, input_builder, __, repository = build_service()
    input_builder.error = StrategyInputError("market breadth missing")

    try:
        service.run(command)
    except HoldingMarketDataMissing as exc:
        assert exc.code == "HOLDING_MARKET_DATA_MISSING"
        assert "market breadth" not in str(exc)
    else:
        raise AssertionError("invalid strategy inputs must fail closed")

    assert repository.saved == []
