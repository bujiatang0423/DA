from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from math import sqrt
from typing import TypeAlias

from backend.app.features.backtests.models import BacktestGroupResult


@dataclass(frozen=True)
class MetricValue:
    value: Decimal | None
    diagnostic: str | None = None


@dataclass(frozen=True)
class MetricBreakdown:
    breakdown: dict[str, Decimal]
    diagnostic: str | None = None


@dataclass(frozen=True)
class AcceptanceGate:
    name: str
    observed: Decimal | int | None
    threshold: Decimal | int | None
    passed: bool
    reason: str


ReportedMetric: TypeAlias = MetricValue | MetricBreakdown


def safe_ratio(numerator: Decimal, denominator: Decimal) -> MetricValue:
    if denominator == 0:
        return MetricValue(value=None, diagnostic="ZERO_DENOMINATOR")
    return MetricValue(value=numerator / denominator)


def closed_trade_gate(count: int) -> AcceptanceGate:
    return AcceptanceGate(
        name="sample_out_closed_trades",
        observed=count,
        threshold=200,
        passed=count >= 200,
        reason="PASSED" if count >= 200 else "INSUFFICIENT_CLOSED_TRADES",
    )


class MetricsReporter:
    """Derive research metrics only from the result's auditable event records."""

    def __init__(
        self,
        initial_cash: Decimal | None = None,
        out_of_sample_start: date | None = None,
    ) -> None:
        if initial_cash is not None and initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self._initial_cash = initial_cash
        self._out_of_sample_start = out_of_sample_start

    def calculate(self, result: BacktestGroupResult) -> dict[str, ReportedMetric]:
        curve = result.equity_curve
        days = _curve_days(curve)
        initial_cash = self._initial_cash or _initial_equity(curve)
        annualized_return = self._annualized_return(curve, days, initial_cash)
        maximum_drawdown = _maximum_drawdown(curve)
        closed_trades = _closed_trades(result.trades)
        notional = _execution_notional(result.trades)

        metrics: dict[str, ReportedMetric] = {
            "annualized_return": annualized_return,
            "maximum_drawdown": maximum_drawdown,
            "recovery": _recovery_duration(curve),
            "calmar": _calmar(annualized_return, maximum_drawdown),
            "profit_factor": _profit_factor(closed_trades),
            "net_win_rate": _net_win_rate(closed_trades),
            "average_win_loss": _average_win_loss(closed_trades),
            "expectancy": _expectancy(closed_trades),
            "turnover": self._annualized_turnover(notional, days, result.trades, initial_cash),
            "costs": MetricValue(sum(_decimal_values(result.trades, "fee"), Decimal(0))),
            "slippage": _slippage(result.trades),
            "average_exposure": _average_curve_value(curve, "exposure"),
            "maximum_industry_exposure": _maximum_curve_value(curve, "industry_exposure"),
            "maximum_risk": _maximum_curve_value(curve, "portfolio_risk"),
            "unfilled_rate": _unfilled_rate(result),
            "limit_block_count": MetricValue(
                Decimal(sum(_is_limit_blocked(attempt) for attempt in result.rejected_attempts))
            ),
            "r_distribution": _r_distribution(closed_trades),
            "market_regime": _market_regime_breakdown(curve),
            "strategy_book": _strategy_book_breakdown(closed_trades),
        }
        return metrics

    def acceptance_gates(self, result: BacktestGroupResult) -> tuple[AcceptanceGate, ...]:
        metrics = self.calculate(result)
        boundary = self._out_of_sample_start or result.out_of_sample_start
        if boundary is None:
            sample_out_gate = AcceptanceGate(
                "sample_out_closed_trades",
                None,
                200,
                False,
                "OUT_OF_SAMPLE_BOUNDARY_REQUIRED",
            )
        else:
            closed_trades, diagnostic = _closed_trades_after(result.trades, boundary)
            sample_out_gate = (
                AcceptanceGate("sample_out_closed_trades", None, 200, False, diagnostic)
                if diagnostic is not None
                else closed_trade_gate(len(closed_trades))
            )
        profit_factor = _metric_value(metrics["profit_factor"])
        expectancy = _metric_value(metrics["expectancy"])
        drawdown = _metric_value(metrics["maximum_drawdown"])
        return (
            sample_out_gate,
            _minimum_gate("net_profit_factor", profit_factor, Decimal("1.30")),
            _strictly_positive_gate("net_expectancy", expectancy),
            _minimum_gate("maximum_drawdown", drawdown, Decimal("-0.25")),
            _not_evaluated_gate("parameter_range_stability", "PARAMETER_STABILITY_NOT_EVALUATED"),
            _not_evaluated_gate("group_d_improvement", "EXPERIMENT_COMPARISON_NOT_EVALUATED"),
            _not_evaluated_gate("average_loss_regression", "BASELINE_LOSS_NOT_EVALUATED"),
            _not_evaluated_gate(
                "year_and_regime_concentration", "PERIOD_CONCENTRATION_NOT_EVALUATED"
            ),
        )

    def _annualized_return(
        self,
        curve: list[dict[str, str]],
        days: int | None,
        initial_cash: Decimal | None,
    ) -> MetricValue:
        if not curve or days is None or days <= 0 or initial_cash is None:
            return MetricValue(None, "INSUFFICIENT_EQUITY_HISTORY")
        final_equity = _decimal(curve[-1].get("equity"))
        if final_equity is None or final_equity <= 0:
            return MetricValue(None, "INVALID_FINAL_EQUITY")
        annualized = ((final_equity / initial_cash).ln() * Decimal(365) / days).exp() - 1
        return MetricValue(annualized)

    def _annualized_turnover(
        self,
        notional: MetricValue,
        days: int | None,
        trades: list[dict[str, str]],
        initial_cash: Decimal | None,
    ) -> MetricValue:
        if not trades:
            return MetricValue(Decimal(0))
        if notional.value is None:
            return notional
        if days is None or days <= 0 or initial_cash is None:
            return MetricValue(None, "INSUFFICIENT_EQUITY_HISTORY")
        return MetricValue(notional.value / initial_cash * Decimal(365) / days)


def calculate_metrics(equity: list[Decimal], initial_cash: Decimal) -> dict[str, str | int | None]:
    """Keep the original event-loop summary stable until structured persistence is added."""
    if not equity:
        return {"total_return": "0", "max_drawdown": "0", "sharpe": None, "observations": 0}
    peak = equity[0]
    max_drawdown = Decimal(0)
    returns: list[Decimal] = []
    for value, previous in zip(equity, [equity[0], *equity[:-1]], strict=True):
        peak = max(peak, value)
        if peak:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
        if previous:
            returns.append(value / previous - 1)
    mean = sum(returns, Decimal(0)) / len(returns) if returns else Decimal(0)
    variance = sum((item - mean) ** 2 for item in returns) / len(returns) if returns else Decimal(0)
    sharpe = (
        mean / Decimal(str(sqrt(float(variance)))) * Decimal(str(sqrt(252))) if variance else None
    )
    return {
        "total_return": str(equity[-1] / initial_cash - 1),
        "max_drawdown": str(max_drawdown),
        "sharpe": str(sharpe) if sharpe is not None else None,
        "observations": len(equity),
    }


def _curve_days(curve: list[dict[str, str]]) -> int | None:
    if len(curve) < 2:
        return None
    try:
        return (
            date.fromisoformat(curve[-1]["trade_date"]) - date.fromisoformat(curve[0]["trade_date"])
        ).days
    except (KeyError, ValueError):
        return None


def _initial_equity(curve: list[dict[str, str]]) -> Decimal | None:
    return _decimal(curve[0].get("equity")) if curve else None


def _maximum_drawdown(curve: list[dict[str, str]]) -> MetricValue:
    values = _decimal_values(curve, "equity")
    if len(values) != len(curve) or not values:
        return MetricValue(None, "MISSING_EQUITY")
    peak = values[0]
    maximum = Decimal(0)
    for value in values:
        peak = max(peak, value)
        if peak == 0:
            return MetricValue(None, "ZERO_EQUITY_PEAK")
        maximum = min(maximum, value / peak - 1)
    return MetricValue(maximum)


def _calmar(return_value: MetricValue, drawdown: MetricValue) -> MetricValue:
    if return_value.value is None:
        return MetricValue(None, return_value.diagnostic)
    if drawdown.value is None:
        return MetricValue(None, drawdown.diagnostic)
    return safe_ratio(return_value.value, abs(drawdown.value))


def _recovery_duration(curve: list[dict[str, str]]) -> MetricValue:
    values = _decimal_values(curve, "equity")
    if len(values) != len(curve) or not values:
        return MetricValue(None, "MISSING_EQUITY")
    peak = values[0]
    peak_index = 0
    drawdown = Decimal(0)
    drawdown_peak_index = 0
    trough_index = 0
    for index, value in enumerate(values):
        if value > peak:
            peak = value
            peak_index = index
        if peak == 0:
            return MetricValue(None, "ZERO_EQUITY_PEAK")
        current_drawdown = value / peak - 1
        if current_drawdown < drawdown:
            drawdown = current_drawdown
            drawdown_peak_index = peak_index
            trough_index = index
    if drawdown == 0:
        return MetricValue(Decimal(0))
    for index in range(trough_index + 1, len(values)):
        if values[index] >= values[drawdown_peak_index]:
            duration = _days_between(curve[drawdown_peak_index], curve[index])
            if duration is None:
                return MetricValue(None, "MISSING_RECOVERY_DATES")
            return MetricValue(Decimal(duration))
    return MetricValue(None, "DRAWDOWN_NOT_RECOVERED")


def _closed_trades(trades: list[dict[str, str]]) -> list[dict[str, str]]:
    return [trade for trade in trades if _decimal(trade.get("realized_net_pnl")) is not None]


def _closed_trades_after(
    trades: list[dict[str, str]], out_of_sample_start: date
) -> tuple[list[dict[str, str]], str | None]:
    closed_trades = _closed_trades(trades)
    parsed_dates = [_trade_date(trade) for trade in closed_trades]
    if any(trade_date is None for trade_date in parsed_dates):
        return [], "MISSING_CLOSED_TRADE_DATE"
    return (
        [
            trade
            for trade, trade_date in zip(closed_trades, parsed_dates, strict=True)
            if trade_date is not None and trade_date >= out_of_sample_start
        ],
        None,
    )


def _profit_factor(trades: list[dict[str, str]]) -> MetricValue:
    pnl = _decimal_values(trades, "realized_net_pnl")
    if len(pnl) != len(trades):
        return MetricValue(None, "MISSING_REALIZED_PNL")
    gross_profit = sum((value for value in pnl if value > 0), Decimal(0))
    gross_loss = -sum((value for value in pnl if value < 0), Decimal(0))
    return safe_ratio(gross_profit, gross_loss)


def _net_win_rate(trades: list[dict[str, str]]) -> MetricValue:
    if not trades:
        return MetricValue(None, "NO_CLOSED_TRADES")
    pnl = _decimal_values(trades, "realized_net_pnl")
    if len(pnl) != len(trades):
        return MetricValue(None, "MISSING_REALIZED_PNL")
    return MetricValue(Decimal(sum(value > 0 for value in pnl)) / len(pnl))


def _average_win_loss(trades: list[dict[str, str]]) -> MetricValue:
    pnl = _decimal_values(trades, "realized_net_pnl")
    if len(pnl) != len(trades):
        return MetricValue(None, "MISSING_REALIZED_PNL")
    wins = [value for value in pnl if value > 0]
    losses = [-value for value in pnl if value < 0]
    if not wins or not losses:
        return MetricValue(None, "MISSING_WIN_OR_LOSS_SAMPLE")
    return safe_ratio(sum(wins, Decimal(0)) / len(wins), sum(losses, Decimal(0)) / len(losses))


def _expectancy(trades: list[dict[str, str]]) -> MetricValue:
    if not trades:
        return MetricValue(None, "NO_CLOSED_TRADES")
    r_multiples = _decimal_values(trades, "r_multiple")
    if len(r_multiples) != len(trades):
        return MetricValue(None, "MISSING_R_MULTIPLE")
    return MetricValue(sum(r_multiples, Decimal(0)) / len(r_multiples))


def _slippage(trades: list[dict[str, str]]) -> MetricValue:
    actual = _decimal_values(trades, "price")
    theoretical = _decimal_values(trades, "theoretical_price")
    quantities = _decimal_values(trades, "quantity")
    if not trades:
        return MetricValue(Decimal(0))
    if (
        len(actual) != len(trades)
        or len(theoretical) != len(trades)
        or len(quantities) != len(trades)
    ):
        return MetricValue(None, "MISSING_EXECUTION_PRICE")
    numerator = sum(
        (
            abs(model - observed) * quantity
            for observed, model, quantity in zip(actual, theoretical, quantities, strict=True)
        ),
        Decimal(0),
    )
    denominator = sum(
        (price * quantity for price, quantity in zip(actual, quantities, strict=True)), Decimal(0)
    )
    return safe_ratio(numerator, denominator)


def _execution_notional(trades: list[dict[str, str]]) -> MetricValue:
    if not trades:
        return MetricValue(Decimal(0))
    values: list[Decimal] = []
    for trade in trades:
        price = _decimal(trade.get("price"))
        quantity = _decimal(trade.get("quantity"))
        if price is None or quantity is None:
            return MetricValue(None, "MISSING_EXECUTION_NOTIONAL")
        values.append(price * quantity)
    return MetricValue(sum(values, Decimal(0)))


def _average_curve_value(curve: list[dict[str, str]], key: str) -> MetricValue:
    values = _decimal_values(curve, key)
    if len(values) != len(curve) or not values:
        return MetricValue(None, f"MISSING_{key.upper()}")
    return MetricValue(sum(values, Decimal(0)) / len(values))


def _maximum_curve_value(curve: list[dict[str, str]], key: str) -> MetricValue:
    values = _decimal_values(curve, key)
    if len(values) != len(curve) or not values:
        return MetricValue(None, f"MISSING_{key.upper()}")
    return MetricValue(max(values))


def _unfilled_rate(result: BacktestGroupResult) -> MetricValue:
    attempts = len(result.trades) + len(result.rejected_attempts)
    return safe_ratio(Decimal(len(result.rejected_attempts)), Decimal(attempts))


def _r_distribution(trades: list[dict[str, str]]) -> MetricBreakdown:
    values = _decimal_values(trades, "r_multiple")
    if len(values) != len(trades):
        return MetricBreakdown({}, "MISSING_R_MULTIPLE")
    return MetricBreakdown(
        {
            "negative": Decimal(sum(value < 0 for value in values)),
            "zero": Decimal(sum(value == 0 for value in values)),
            "positive": Decimal(sum(value > 0 for value in values)),
        }
    )


def _market_regime_breakdown(curve: list[dict[str, str]]) -> MetricBreakdown:
    regimes = [entry.get("market_regime") for entry in curve]
    if len(curve) < 2 or any(regime not in {"bull", "neutral", "bear"} for regime in regimes[1:]):
        return MetricBreakdown({}, "MISSING_MARKET_REGIME")
    values = _decimal_values(curve, "equity")
    if len(values) != len(curve):
        return MetricBreakdown({}, "MISSING_EQUITY")
    performance = {"bull": Decimal(1), "neutral": Decimal(1), "bear": Decimal(1)}
    for previous, current, regime in zip(values[:-1], values[1:], regimes[1:], strict=True):
        if previous == 0:
            return MetricBreakdown({}, "ZERO_EQUITY")
        performance[str(regime)] *= current / previous
    return MetricBreakdown({regime: value - 1 for regime, value in performance.items()})


def _strategy_book_breakdown(trades: list[dict[str, str]]) -> MetricBreakdown:
    books = [trade.get("strategy_book") for trade in trades]
    if not trades or any(not book for book in books):
        return MetricBreakdown({}, "MISSING_STRATEGY_BOOK")
    pnl = _decimal_values(trades, "realized_net_pnl")
    if len(pnl) != len(trades):
        return MetricBreakdown({}, "MISSING_REALIZED_PNL")
    return MetricBreakdown(
        {
            str(book): sum(
                (
                    _decimal(trade.get("realized_net_pnl")) or Decimal(0)
                    for trade in trades
                    if trade.get("strategy_book") == book
                ),
                Decimal(0),
            )
            for book in sorted(set(books))
        }
    )


def _minimum_gate(name: str, observed: Decimal | None, threshold: Decimal) -> AcceptanceGate:
    if observed is None:
        return AcceptanceGate(name, None, threshold, False, "METRIC_NOT_AVAILABLE")
    return AcceptanceGate(
        name,
        observed,
        threshold,
        observed >= threshold,
        "PASSED" if observed >= threshold else "BELOW_THRESHOLD",
    )


def _strictly_positive_gate(name: str, observed: Decimal | None) -> AcceptanceGate:
    if observed is None:
        return AcceptanceGate(name, None, Decimal(0), False, "METRIC_NOT_AVAILABLE")
    return AcceptanceGate(
        name, observed, Decimal(0), observed > 0, "PASSED" if observed > 0 else "NOT_POSITIVE"
    )


def _not_evaluated_gate(name: str, reason: str) -> AcceptanceGate:
    return AcceptanceGate(name, None, None, False, reason)


def _metric_value(metric: ReportedMetric) -> Decimal | None:
    return metric.value if isinstance(metric, MetricValue) else None


def _decimal_values(records: list[dict[str, str]], key: str) -> list[Decimal]:
    return [value for record in records if (value := _decimal(record.get(key))) is not None]


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _is_limit_blocked(attempt: dict[str, str]) -> bool:
    return attempt.get("reason_code", "").startswith("LIMIT_")


def _days_between(start: dict[str, str], end: dict[str, str]) -> int | None:
    try:
        return (
            date.fromisoformat(end["trade_date"]) - date.fromisoformat(start["trade_date"])
        ).days
    except (KeyError, ValueError):
        return None


def _trade_date(trade: dict[str, str]) -> date | None:
    try:
        return date.fromisoformat(trade["trade_date"])
    except (KeyError, ValueError):
        return None
