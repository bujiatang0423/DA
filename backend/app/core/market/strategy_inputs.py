from __future__ import annotations

from dataclasses import fields, replace
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
    PolicyEvidence,
    PolicyStage,
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
    for previous, current in zip(ordered, ordered[1:], strict=False):
        high, low = float(current["high"]), float(current["low"])
        trs.append(
            max(
                high - low,
                abs(high - float(previous["close"])),
                abs(low - float(previous["close"])),
            )
        )
    return mean(tuple(trs[-14:]))


def obv_slope(bars: tuple[dict[str, Any], ...], window: int = 20) -> float:
    if len(bars) < window + 1:
        return 0.0
    obv = 0.0
    values: list[float] = []
    for previous, current in zip(bars[-window - 1 :], bars[-window:], strict=True):
        if float(current.get("close", 0)) > float(previous.get("close", 0)):
            obv += float(current.get("volume", current.get("vol", 0)))
        elif float(current.get("close", 0)) < float(previous.get("close", 0)):
            obv -= float(current.get("volume", current.get("vol", 0)))
        values.append(obv)
    return (values[-1] - values[0]) / max(1.0, abs(values[0]))


def winsorized_percentile(values: tuple[float, ...], value: float) -> float:
    if not values:
        return 0.5
    low, high = (
        sorted(values)[max(0, int(len(values) * 0.01) - 1)],
        sorted(values)[min(len(values) - 1, int(len(values) * 0.99))],
    )
    clipped = min(high, max(low, value))
    return sum(item <= clipped for item in values) / len(values)


def _payload(record: TemporalRecord) -> dict[str, Any]:
    return dict(record.payload)


def _bars(snapshot: PointInTimeSnapshot, security_id: str) -> tuple[dict[str, Any], ...]:
    rows = (
        [
            _payload(r)
            for r in snapshot.security_observations_by_id(security_id).records_of(
                DataKind.DAILY_BAR_RAW
            )
        ]
        if hasattr(snapshot, "security_observations_by_id")
        else []
    )
    if not rows:
        observation = next(
            (x for x in snapshot.security_observations if x.security_id == security_id), None
        )
        rows = (
            [_payload(r) for r in observation.records_of(DataKind.DAILY_BAR_RAW)]
            if observation
            else []
        )
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
        if not any("breadth" in p or p.get("security_count") is not None for p in market_payloads):
            raise StrategyInputError("market breadth missing")

        securities: list[SecurityEvaluationInput] = []
        global_policy = tuple(
            r for r in snapshot.market_inputs if r.kind is DataKind.POLICY_DOCUMENT
        )
        global_llm = tuple(r for r in snapshot.market_inputs if r.kind is DataKind.LLM_FACTOR)
        all_returns20: list[float] = []
        all_returns60: list[float] = []
        returns_by_security: dict[str, tuple[float, float]] = {}
        for observation in snapshot.security_observations:
            master = next(
                (r for r in observation.records if r.kind is DataKind.SECURITY_MASTER), None
            )
            bars = _bars(snapshot, observation.security_id)
            closes = tuple(float(x.get("close", 0)) for x in bars if x.get("close") is not None)
            if len(closes) >= 60 and closes[0] > 0:
                r20 = closes[-1] / closes[-21] - 1 if len(closes) >= 21 else 0.0
                r60 = closes[-1] / closes[-60] - 1
                all_returns20.append(r20)
                all_returns60.append(r60)
                returns_by_security[observation.security_id] = (r20, r60)
            complete = len(observation.records_of(DataKind.FINANCIAL_FACT)) >= 2
            quality: list[str] = []
            if not bars:
                quality.append("MARKET_DATA_UNAVAILABLE")
            if not complete:
                quality.append("FINANCIAL_TEMPLATE_INCOMPLETE")
            financial_rows = [_payload(r) for r in observation.records_of(DataKind.FINANCIAL_FACT)]
            numeric_values = [
                float(v)
                for row in financial_rows
                for v in row.values()
                if isinstance(v, (int, float))
            ]
            financial_score = max(0.0, min(100.0, mean(numeric_values))) if numeric_values else 0.0
            if not numeric_values:
                quality.append("FINANCIAL_NUMERIC_MISSING")
                quality.append("FINANCIAL_DATA_UNAVAILABLE")
            policy_records = observation.records_of(DataKind.POLICY_DOCUMENT) + tuple(
                r
                for r in global_policy
                if observation.security_id in str(_payload(r).get("security_ids", ""))
            )
            llm_records = observation.records_of(DataKind.LLM_FACTOR) + tuple(
                r
                for r in global_llm
                if observation.security_id in str(_payload(r).get("security_ids", ""))
            )
            llm_valid = bool(llm_records) and all(
                str(_payload(r).get("first_observed_at", "")) <= snapshot.as_of_time.isoformat()
                for r in llm_records
            )
            policy_available = bool(policy_records)
            if not policy_available:
                quality.append("POLICY_EVIDENCE_INVALID")
            if not llm_valid:
                quality.append("LLM_FACTOR_INVALID")
            name = str(_payload(master).get("name", "")) if master else ""
            master_payload = _payload(master) if master else {}
            industry = (
                str(_payload(master).get("industry_id", _payload(master).get("industry", "")))
                if master
                else ""
            )
            close = closes[-1] if closes else 0.0
            ma20 = moving_average(closes, 20) if len(closes) >= 20 else 0.0
            ma60 = moving_average(closes, 60) if len(closes) >= 60 else 0.0
            atr = atr14(bars) if len(bars) >= 15 else 0.0
            volumes = tuple(float(x.get("volume", x.get("vol", 0)) or 0) for x in bars)
            amounts = tuple(float(x.get("amount", x.get("turnover", 0)) or 0) for x in bars)
            mavol20 = mean(volumes[-20:]) if len(volumes) >= 20 else 0.0
            average_turnover20 = mean(amounts[-20:]) if len(amounts) >= 20 else 0.0
            recent_high = max((float(x.get("high", 0)) for x in bars[-21:-1]), default=0.0)
            prior_ma20 = mean(closes[-25:-5]) if len(closes) >= 25 else ma20
            volume_percentile = (
                winsorized_percentile(tuple(volumes[-60:]), volumes[-1]) if volumes else 0.0
            )
            turnover_percentile = (
                winsorized_percentile(tuple(amounts[-60:]), amounts[-1]) if amounts else 0.0
            )
            obv_value = obv_slope(bars)
            status = str(master_payload.get("status", "")).upper()
            listing_days = int(master_payload.get("listing_days", 9999) or 0)
            one_word = len(bars) > 0 and all(
                float(x.get("high", 0)) == float(x.get("low", 1)) for x in bars[-5:]
            )
            hard_market = (
                "ST" not in name.upper()
                and "*ST" not in name.upper()
                and listing_days >= 120
                and len(bars) >= 18
                and mavol20 > 0
                and average_turnover20 >= 50_000_000
                and status not in {"SUSPENDED", "停牌"}
                and close > 0
                and not one_word
            )
            llm_payload = _payload(llm_records[-1]) if llm_records else {}
            values: dict[str, Any] = {f.name: 0 for f in fields(SecurityEvaluationInput)}
            values.update(
                security_id=observation.security_id,
                name=name,
                industry=industry,
                theme=None,
                ledger=LedgerKind.CORE,
                financial_light=FinancialLight.GREEN if complete else FinancialLight.YELLOW,
                policy_evidence=tuple(
                    PolicyEvidence(
                        float(_payload(r).get("strength", 0.0)),
                        float(_payload(r).get("relevance", 0.0)),
                        int(_payload(r).get("age_days", 0)),
                        PolicyStage(str(_payload(r).get("stage", "planning")))
                        if str(_payload(r).get("stage", "planning"))
                        in {x.value for x in PolicyStage}
                        else PolicyStage.PLANNING,
                        float(_payload(r).get("evidence_confidence", 0.0)),
                        float(_payload(r).get("data_completeness", 0.0)),
                    )
                    for r in policy_records
                ),
                financial_numeric_score=financial_score,
                financial_text_score=100.0 if complete else 0.0,
                policy_direction=str(llm_payload.get("policy_direction", "unknown")),
                rs20_percentile=0.0,
                rs60_percentile=0.0,
                industry_proxy=False,
                above_ma20=bool(close > ma20 > 0),
                above_ma60=bool(close > ma60 > 0),
                rising_ma20=bool(ma20 >= prior_ma20 > 0),
                breakout_or_valid_pullback=bool(close >= recent_high > 0 or close > ma20 > 0),
                ma20_atr_distance=(close - ma20) / atr if atr > 0 else 0.0,
                breakout_volume_percentile=volume_percentile,
                obv_slope_percentile=max(0.0, min(1.0, (obv_value + 1.0) / 2.0)),
                turnover_percentile=turnover_percentile,
                planned_price=close,
                close=close,
                ma20=ma20,
                ma60=ma60,
                atr14=atr,
                average_turnover20=average_turnover20,
                pullback_low=min((float(x.get("low", close)) for x in bars[-10:]), default=close),
                red_light=bool(llm_payload.get("red_light", False)),
                hard_filter_passed=hard_market and complete and policy_available and llm_valid,
                policy_sources_available=policy_available,
                llm_factor_valid=llm_valid,
                held=any(p.security_id == observation.security_id for p in portfolio.positions),
                quality_codes=tuple(quality),
            )
            securities.append(SecurityEvaluationInput(**values))

        breadth = next(
            (float(p["breadth"]) for p in market_payloads if p.get("breadth") is not None), 0.0
        )
        if all_returns20 and all_returns60:
            securities = [
                replace(
                    s,
                    rs20_percentile=winsorized_percentile(
                        tuple(all_returns20), returns_by_security.get(s.security_id, (0.0, 0.0))[0]
                    ),
                    rs60_percentile=winsorized_percentile(
                        tuple(all_returns60), returns_by_security.get(s.security_id, (0.0, 0.0))[1]
                    ),
                )
                for s in securities
            ]
        index_close = next(
            (float(p["close"]) for p in market_payloads if p.get("close") is not None), 0.0
        )
        rows = next((p.get("bars", ()) for p in market_payloads if p.get("bars")), ())
        idx = tuple(float(x.get("close", 0)) for x in rows)
        ma20 = mean(idx[-20:]) if len(idx) >= 20 else 0.0
        ma60 = mean(idx[-60:]) if len(idx) >= 60 else 0.0
        ret1 = idx[-1] / idx[-2] - 1 if len(idx) >= 2 else 0.0
        ret20 = idx[-1] / idx[-21] - 1 if len(idx) >= 21 else 0.0
        state = (
            MarketState.STRONG
            if index_close > ma20 > ma60 > 0
            else MarketState.WEAK
            if ma20 and index_close < ma20
            else MarketState.NEUTRAL
        )
        market = MarketRegimeInput(
            index_close,
            ma20,
            ret1,
            ret20,
            breadth,
            0.0,
            0.0,
            0,
            0.0,
            0.0,
            0.0,
            0,
            0,
            False,
            state,
            0,
            False,
        )
        pview = PortfolioView(float(portfolio.equity), 0.0, 0.0, len(portfolio.positions))
        return StrategyEvaluationRequest(
            AsOf(as_of_time=snapshot.as_of_time),
            StrategyVersion(version=strategy_version, sha256=snapshot.manifest_hash),
            snapshot.manifest_hash,
            market,
            pview,
            tuple(securities),
        )
