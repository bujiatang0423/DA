from __future__ import annotations

from decimal import Decimal
from math import sqrt


def calculate_metrics(equity: list[Decimal], initial_cash: Decimal) -> dict[str, str | int | None]:
    if not equity:
        return {"total_return": "0", "max_drawdown": "0", "sharpe": None, "observations": 0}
    peak = equity[0]
    max_dd = Decimal(0)
    returns: list[Decimal] = []
    for value, previous in zip(equity, [equity[0], *equity[:-1]], strict=True):
        peak = max(peak, value)
        if peak:
            max_dd = max(max_dd, (peak - value) / peak)
        if previous:
            returns.append(value / previous - 1)
    mean = sum(returns, Decimal(0)) / len(returns) if returns else Decimal(0)
    variance = sum((x - mean) ** 2 for x in returns) / len(returns) if returns else Decimal(0)
    sharpe = (
        (mean / Decimal(str(sqrt(float(variance)))) * Decimal(str(sqrt(252)))) if variance else None
    )
    return {
        "total_return": str(equity[-1] / initial_cash - 1),
        "max_drawdown": str(max_dd),
        "sharpe": str(sharpe) if sharpe is not None else None,
        "observations": len(equity),
    }
