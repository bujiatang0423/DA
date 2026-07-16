from .types import *
from .market_regime import evaluate_market_regime
from .factors import *
from .risk import size_position
from .constraints import check_constraints
from .reason_codes import ReasonCode


class V212StrategyEngine:
    def evaluate(self, request: StrategyEvaluationRequest) -> StrategyEvaluation:
        market = evaluate_market_regime(request.market)
        raw = []
        for s in request.securities:
            p = policy_score(s.policy_evidence)
            f = financial_score(
                s.financial_numeric_score, s.financial_text_score, s.financial_light
            )
            q = list(s.quality_codes)
            reasons = []
            factors = None
            sizing = None
            if not s.hard_filter_passed:
                q.append("HARD_FILTER")
            if not s.policy_sources_available:
                q.append("POLICY_UNAVAILABLE")
                reasons.append(ReasonCode.POLICY_UNAVAILABLE)
            if f is None or not s.llm_factor_valid:
                q.append("FINANCIAL_INVALID")
            if not q and p is not None and f is not None:
                r = relative_strength_score(
                    s.rs20_percentile, s.rs60_percentile, industry_proxy=s.industry_proxy
                )
                t = trend_score(
                    s.above_ma20,
                    s.above_ma60,
                    s.rising_ma20,
                    s.breakout_or_valid_pullback,
                    ma20_atr_distance=s.ma20_atr_distance,
                )
                v = volume_score(
                    s.breakout_volume_percentile, s.obv_slope_percentile, s.turnover_percentile
                )
                score = composite_score(p, f, r, t, v)
                factors = FactorScores(p, f, r, t, v, score, 0)
                sizing = size_position(
                    PositionSizingInput(
                        request.portfolio.net_equity,
                        s.planned_price,
                        s.pullback_low,
                        s.atr14,
                        s.average_turnover20,
                        s.ledger,
                    )
                )
            raw.append((s, factors, sizing, reasons, q))
        scores = tuple(x[1].s if x[1] else 0 for x in raw)
        out = []
        for s, fac, size, reasons, q in raw:
            pct = percentile_rank(scores, fac.s) if fac else 0
            fac = FactorScores(fac.p, fac.f, fac.r, fac.t, fac.v, fac.s, pct) if fac else None
            cons = check_constraints(
                ConstraintInput(
                    request.portfolio,
                    market.max_exposure,
                    s.ledger,
                    s.industry,
                    s.theme,
                    size.notional if size else 0,
                    size.order_risk if size else 0,
                    False,
                )
            )
            out.append(
                SecurityEvaluation(
                    s.security_id,
                    s.name,
                    s.industry,
                    s.theme,
                    fac,
                    market.state,
                    s.hard_filter_passed,
                    s.policy_sources_available,
                    s.llm_factor_valid,
                    s.financial_light,
                    s.policy_direction,
                    s.breakout_confirmed,
                    s.pullback_confirmed,
                    s.strengthened_confirmed,
                    s.days_since_breakout,
                    s.held,
                    s.close,
                    s.ma20,
                    s.ma60,
                    s.atr14,
                    s.r_multiple,
                    pct,
                    s.red_light,
                    s.hard_stop,
                    s.market_reduction,
                    s.book_exit,
                    s.rank_exit,
                    s.stop_raise_required,
                    size,
                    cons,
                    tuple(q),
                    tuple(reasons),
                )
            )
        out.sort(key=lambda x: (-(x.factors.s if x.factors else 0), x.security_id))
        return StrategyEvaluation(
            request.as_of.as_of_time,
            request.strategy.version,
            request.manifest_hash,
            market,
            tuple(out),
        )
