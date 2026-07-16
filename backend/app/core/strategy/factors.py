from math import exp
from .types import *


def policy_score(e: tuple[PolicyEvidence, ...]) -> float | None:
    if not e or any(x.stage is PolicyStage.EXIT for x in e):
        return None
    vals = []
    for x in e:
        h, s = {
            PolicyStage.PLANNING: (20, 0.6),
            PolicyStage.PILOT: (40, 0.8),
            PolicyStage.EXECUTION: (60, 1),
            PolicyStage.MATURE: (30, 0.7),
        }[x.stage]
        raw = 50 + (x.strength - 50) * x.relevance / 100
        d = 50 + (raw - 50) * exp(-x.age_days / h)
        score = 50 + (d - 50) * s * x.evidence_confidence * x.data_completeness
        w = x.evidence_confidence * x.data_completeness * exp(-x.age_days / h)
        vals.append((score, w))
    den = sum(w for _, w in vals)
    return 50 if den == 0 else sum(s * w for s, w in vals) / den


def financial_score(n: float, t: float, l: FinancialLight) -> float | None:
    if l is FinancialLight.RED:
        return None
    s = 0.7 * n + 0.3 * t
    return min(s, 65) if l is FinancialLight.YELLOW else s


def relative_strength_score(a: float, b: float, *, industry_proxy: bool) -> float:
    return (0.5 * a + 0.5 * b) * (0.9 if industry_proxy else 1)


def trend_score(a: bool, b: bool, c: bool, d: bool, *, ma20_atr_distance: float) -> float:
    s = 25 * sum((a, b, c, d))
    return max(0, s - 20) if ma20_atr_distance > 2.5 else s


def volume_score(a: float, b: float, c: float) -> float:
    return 0.5 * a + 0.3 * b + 0.2 * c


def composite_score(p: float, f: float, r: float, t: float, v: float) -> float:
    return 0.2 * p + 0.2 * f + 0.25 * r + 0.2 * t + 0.15 * v


def percentile_rank(values: tuple[float, ...], value: float) -> float:
    if not values:
        raise ValueError("cross section cannot be empty")
    return (
        100 * (sum(x < value for x in values) + 0.5 * sum(x == value for x in values)) / len(values)
    )
