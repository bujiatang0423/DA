from .types import *
from .reason_codes import ReasonCode


def check_constraints(v: ConstraintInput) -> ConstraintDecision:
    p = v.portfolio
    w = v.order_notional / p.net_equity
    risk = v.order_risk / p.net_equity
    r = []
    if p.position_count >= 6:
        r.append(ReasonCode.POSITION_COUNT_LIMIT)
    if w > (0.15 if v.ledger is LedgerKind.CORE else 0.12):
        r.append(ReasonCode.SECURITY_WEIGHT_LIMIT)
    if not v.is_broad_etf and p.industry_weights.get(v.industry, 0) + w > 0.25:
        r.append(ReasonCode.INDUSTRY_WEIGHT_LIMIT)
    if v.theme and p.theme_weights.get(v.theme, 0) + w > 0.3:
        r.append(ReasonCode.THEME_WEIGHT_LIMIT)
    if p.gross_exposure + w > v.market_max_exposure:
        r.append(ReasonCode.MARKET_EXPOSURE_LIMIT)
    if p.portfolio_risk + risk > 0.03:
        r.append(ReasonCode.PORTFOLIO_RISK_LIMIT)
    return ConstraintDecision(not r, tuple(r))
