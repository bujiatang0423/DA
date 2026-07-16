from .reason_codes import ReasonCode
from .types import *
def evaluate_market_regime(v:MarketRegimeInput)->MarketRegimeDecision:
    raw=MarketState.STRONG if v.index_close>v.index_ma60 and v.index_ma20>v.index_ma20_5d_ago and v.breadth>=.55 else MarketState.WEAK if v.index_close<v.index_ma60 and v.breadth<.4 else MarketState.NEUTRAL
    state=raw if raw==v.current_state or v.candidate_streak>=2 else v.current_state; maximum={MarketState.STRONG:.9 if v.breadth>=.65 and v.index_close>v.index_ma20 else .8,MarketState.NEUTRAL:.6 if v.breadth>=.5 else .5,MarketState.WEAK:0 if v.breadth<.3 else .2}[state]
    reasons=[]; stop=v.index_return_1d<-.04 or v.limit_down_count>500 or v.portfolio_open_drawdown>=.03
    if v.low_confidence: maximum={MarketState.STRONG:.7,MarketState.NEUTRAL:.4,MarketState.WEAK:0}[state]; reasons.append(ReasonCode.MARKET_LOW_CONFIDENCE)
    week=max(v.week_cooldown_remaining,5 if v.portfolio_week_drawdown>=.06 else -1); month=max(v.month_cooldown_remaining,10 if v.portfolio_month_drawdown>=.1 else -1)
    if week>0 or (week==0 and not v.cooldown_recovery_confirmed): maximum=min(maximum,.4); stop=True
    if month>0 or (month==0 and not v.cooldown_recovery_confirmed): maximum=min(maximum,.2); stop=True
    if stop: reasons.append(ReasonCode.SYSTEMIC_RISK_OVERLAY)
    return MarketRegimeDecision(state,maximum,state is not MarketState.WEAK and not stop,state is MarketState.STRONG and not stop,"low" if v.low_confidence else "normal",week,month,tuple(reasons))
