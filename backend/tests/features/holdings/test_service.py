from dataclasses import replace
from decimal import Decimal

import pytest

from backend.app.core.market.pit_models import (
    DataKind,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
)
from backend.app.core.market.strategy_inputs import StrategyInputError
from backend.app.core.strategy.types import PortfolioView
from backend.app.features.holdings.models import AdviceAction
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


def test_service_projects_the_strategy_portfolio_summary_without_recalculation() -> None:
    service, command, _, _, _, strategy, _ = build_service()
    strategy.evaluation = replace(
        strategy.evaluation,
        portfolio_summary=PortfolioView(
            net_equity=1_000_000,
            gross_exposure=0.42,
            portfolio_risk=0.009,
            position_count=1,
        ),
    )

    result = service.run(command)

    assert result.summary.gross_exposure_pct == Decimal("42.0")
    assert result.summary.portfolio_risk_pct == Decimal("0.9")


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
