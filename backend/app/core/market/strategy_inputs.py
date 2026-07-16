from __future__ import annotations

from dataclasses import fields
from statistics import mean
from typing import Any

from backend.app.contracts.strategy import AsOf, StrategyVersion
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot, TemporalRecord
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import (
    FinancialLight,
    LedgerKind,
    MarketRegimeInput,
    MarketState,
    PortfolioView,
    SecurityEvaluationInput,
    StrategyEvaluationRequest,
)


class StrategyInputError(ValueError):
    pass


def moving_average(values: tuple[float, ...], window: int) -> float:
    if len(values) < window:
        raise StrategyInputError(f"insufficient data for MA{window}")
    return mean(values[-window:])


def atr14(bars: tuple[dict[str, Any], ...]) -> float:
    if len(bars) < 15:
        raise StrategyInputError("insufficient data for ATR14")
    ordered = bars[-15:]
    trs = []
    for previous, current in zip(ordered, ordered[1:], strict=True):
        high, low = float(current["high"]), float(current["low"])
        trs.append(max(high - low, abs(high - float(previous["close"])), abs(low - float(previous["close"]))))
    return mean(tuple(trs[-14:]))


def winsorized_percentile(values: tuple[float, ...], value: float) -> float:
    if not values:
        return 0.5
    low, high = sorted(values)[max(0, int(len(values) * 0.01) - 1)], sorted(values)[min(len(values) - 1, int(len(values) * 0.99))]
    clipped = min(high, max(low, value))
    return sum(item <= clipped for item in values) / len(values)


def _payload(record: TemporalRecord) -> dict[str, Any]:
    return dict(record.payload)


def _bars(snapshot: PointInTimeSnapshot, security_id: str) -> tuple[dict[str, Any], ...]:
    rows = [_payload(r) for r in snapshot.security_observations_by_id(security_id).records_of(DataKind.DAILY_BAR_RAW)] if hasattr(snapshot, "security_observations_by_id") else []
    if not rows:
        observation = next((x for x in snapshot.security_observations if x.security_id == security_id), None)
        rows = [_payload(r) for r in observation.records_of(DataKind.DAILY_BAR_RAW)] if observation else []
    return tuple(sorted(rows, key=lambda x: str(x.get("trade_date", x.get("date", "")))))


class StrategyInputBuilder:
    def build(
        self,
        *,
        snapshot: PointInTimeSnapshot,
        portfolio: PortfolioSnapshot,
        strategy_version: str,
    ) -> StrategyEvaluationRequest:
        if snapshot.quality.has_errors:
            raise StrategyInputError("snapshot quality contains errors")
        market_payloads = [_payload(r) for r in snapshot.market_inputs]
        if not any(r.kind is DataKind.TRADING_CALENDAR for r in snapshot.market_inputs) and not any(
            "breadth" in p or p.get("security_count") is not None for p in market_payloads
        ):
            raise StrategyInputError("market breadth missing")

        securities: list[SecurityEvaluationInput] = []
        all_returns20: list[float] = []
        all_returns60: list[float] = []
        for observation in snapshot.security_observations:
            master = next((r for r in observation.records if r.kind is DataKind.SECURITY_MASTER), None)
            bars = _bars(snapshot, observation.security_id)
            closes = tuple(float(x.get("close", 0)) for x in bars if x.get("close") is not None)
            if len(closes) >= 60 and closes[0] > 0:
                all_returns20.append(closes[-1] / closes[-21] - 1 if len(closes) >= 21 else 0.0)
                all_returns60.append(closes[-1] / closes[-60] - 1)
            complete = len(observation.records_of(DataKind.FINANCIAL_FACT)) >= 2
            quality: list[str] = []
            if not complete:
                quality.append("FINANCIAL_TEMPLATE_INCOMPLETE")
            policy_records = observation.records_of(DataKind.POLICY_DOCUMENT)
            llm_records = observation.records_of(DataKind.LLM_FACTOR)
            llm_valid = bool(llm_records)
            policy_available = bool(policy_records)
            if not policy_available:
                quality.append("POLICY_EVIDENCE_INVALID")
            if not llm_valid:
                quality.append("LLM_FACTOR_INVALID")
            name = str(_payload(master).get("name", "")) if master else ""
            industry = str(_payload(master).get("industry_id", _payload(master).get("industry", ""))) if master else ""
            close = closes[-1] if closes else 0.0
            ma20 = moving_average(closes, 20) if len(closes) >= 20 else 0.0
            ma60 = moving_average(closes, 60) if len(closes) >= 60 else 0.0
            atr = atr14(bars) if len(bars) >= 15 else 0.0
            values: dict[str, Any] = {f.name: 0 for f in fields(SecurityEvaluationInput)}
            values.update(
                security_id=observation.security_id,
                name=name,
                industry=industry,
                theme=None,
                ledger=LedgerKind.CORE,
                financial_light=FinancialLight.UNKNOWN,
                policy_direction="unknown",
                close=close,
                planned_price=close,
                ma20=ma20,
                ma60=ma60,
                atr14=atr,
                hard_filter_passed=complete and policy_available and llm_valid,
                policy_sources_available=policy_available,
                llm_factor_valid=llm_valid,
                held=any(p.security_id == observation.security_id for p in portfolio.positions),
                quality_codes=tuple(quality),
            )
            securities.append(SecurityEvaluationInput(**values))

        breadth = next((float(p["breadth"]) for p in market_payloads if p.get("breadth") is not None), 0.0)
        index_close = next((float(p["close"]) for p in market_payloads if p.get("close") is not None), 0.0)
        market = MarketRegimeInput(index_close, 0.0, 0.0, 0.0, breadth, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0, 0, False, MarketState.NEUTRAL, 0, False)
        pview = PortfolioView(float(portfolio.equity), 0.0, 0.0, len(portfolio.positions))
        return StrategyEvaluationRequest(AsOf(as_of_time=snapshot.as_of_time), StrategyVersion(version=strategy_version, sha256=snapshot.manifest_hash), snapshot.manifest_hash, market, pview, tuple(securities))
