from datetime import date
from decimal import Decimal

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.backtests.metrics import MetricsReporter, closed_trade_gate, safe_ratio
from backend.app.features.backtests.models import BacktestGroupResult, StrategyGroup


def _fixed_metric_result() -> BacktestGroupResult:
    return BacktestGroupResult(
        group=StrategyGroup.D,
        data_grade=DataGrade.RESEARCH,
        llm_grade=LlmGrade.RECONSTRUCTED,
        input_manifest_hash="fixture-manifest",
        equity_curve=[
            {
                "trade_date": "2023-01-03",
                "equity": "100",
                "exposure": "0.50",
                "industry_exposure": "0.20",
                "portfolio_risk": "0.010",
                "market_regime": "bull",
            },
            {
                "trade_date": "2023-07-03",
                "equity": "125",
                "exposure": "0.70",
                "industry_exposure": "0.35",
                "portfolio_risk": "0.012",
                "market_regime": "neutral",
            },
            {
                "trade_date": "2023-12-29",
                "equity": "100",
                "exposure": "0.60",
                "industry_exposure": "0.30",
                "portfolio_risk": "0.011",
                "market_regime": "bear",
            },
            {
                "trade_date": "2024-01-03",
                "equity": "110",
                "exposure": "0.60",
                "industry_exposure": "0.25",
                "portfolio_risk": "0.009",
                "market_regime": "bull",
            },
        ],
        trades=[
            {
                "trade_date": "2023-07-03",
                "side": "sell",
                "quantity": "1",
                "price": "15",
                "theoretical_price": "15.015",
                "fee": "10",
                "realized_net_pnl": "20",
                "r_multiple": "1",
                "strategy_book": "growth",
            },
            {
                "trade_date": "2024-01-03",
                "side": "sell",
                "quantity": "1",
                "price": "15",
                "theoretical_price": "15.015",
                "fee": "5.20",
                "realized_net_pnl": "-10",
                "r_multiple": "-0.50",
                "strategy_book": "value",
            },
            {
                "trade_date": "2024-01-04",
                "side": "buy",
                "quantity": "1",
                "price": "10",
                "theoretical_price": "10.01",
                "fee": "0",
                "strategy_book": "growth",
            },
        ],
        rejected_attempts=[
            {"reason_code": "LIMIT_UP_LOCKED"},
        ],
        metrics={},
    )


def test_hand_calculated_metrics_use_only_auditable_values() -> None:
    observed = MetricsReporter().calculate(_fixed_metric_result())

    expected = {
        "annualized_return": Decimal("0.10"),
        "maximum_drawdown": Decimal("-0.20"),
        "calmar": Decimal("0.50"),
        "profit_factor": Decimal("2.00"),
        "net_win_rate": Decimal("0.50"),
        "average_win_loss": Decimal("2.00"),
        "expectancy": Decimal("0.25"),
        "turnover": Decimal("0.40"),
        "costs": Decimal("15.20"),
        "slippage": Decimal("0.001"),
        "average_exposure": Decimal("0.60"),
        "maximum_industry_exposure": Decimal("0.35"),
        "maximum_risk": Decimal("0.012"),
        "unfilled_rate": Decimal("0.25"),
        "limit_block_count": Decimal("1"),
    }

    assert {name: observed[name].value for name in expected} == expected
    assert observed["recovery"].value is None
    assert observed["recovery"].diagnostic == "DRAWDOWN_NOT_RECOVERED"
    assert observed["r_distribution"].breakdown == {
        "negative": Decimal("1"),
        "zero": Decimal("0"),
        "positive": Decimal("1"),
    }
    assert observed["market_regime"].breakdown == {
        "bear": Decimal("-0.20"),
        "bull": Decimal("0.10"),
        "neutral": Decimal("0.25"),
    }
    assert observed["strategy_book"].breakdown == {
        "growth": Decimal("20"),
        "value": Decimal("-10"),
    }


def test_zero_denominator_and_sample_size_fail_closed() -> None:
    assert safe_ratio(Decimal("1"), Decimal("0")).diagnostic == "ZERO_DENOMINATOR"
    assert closed_trade_gate(199).passed is False
    assert closed_trade_gate(200).passed is True


def test_sample_out_gate_requires_an_explicit_boundary() -> None:
    gates = MetricsReporter().acceptance_gates(_fixed_metric_result())

    sample_out = gates[0]
    assert sample_out.observed is None
    assert sample_out.passed is False
    assert sample_out.reason == "OUT_OF_SAMPLE_BOUNDARY_REQUIRED"


def test_sample_out_gate_fails_closed_when_a_closed_trade_lacks_its_date() -> None:
    result = _fixed_metric_result()
    result.trades[0].pop("trade_date")

    gates = MetricsReporter(out_of_sample_start=date(2023, 1, 3)).acceptance_gates(result)

    assert gates[0].passed is False
    assert gates[0].reason == "MISSING_CLOSED_TRADE_DATE"


def test_sample_out_profit_factor_and_expectancy_exclude_in_sample_wins() -> None:
    gates = MetricsReporter(out_of_sample_start=date(2024, 1, 1)).acceptance_gates(
        _fixed_metric_result()
    )

    profit_factor = next(gate for gate in gates if gate.name == "net_profit_factor")
    expectancy = next(gate for gate in gates if gate.name == "net_expectancy")
    assert profit_factor.observed == Decimal("0")
    assert profit_factor.passed is False
    assert expectancy.observed == Decimal("-0.50")
    assert expectancy.passed is False


def test_recovery_reports_days_from_peak_to_full_recovery() -> None:
    result = _fixed_metric_result()
    result.equity_curve[-1]["equity"] = "125"

    observed = MetricsReporter().calculate(result)

    assert observed["recovery"].value == Decimal("184")


def test_missing_execution_price_does_not_produce_partial_turnover() -> None:
    result = _fixed_metric_result()
    result.trades[-1].pop("price")

    observed = MetricsReporter().calculate(result)

    assert observed["turnover"].diagnostic == "MISSING_EXECUTION_NOTIONAL"
