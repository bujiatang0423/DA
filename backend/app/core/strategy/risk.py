from math import floor
from .types import *
from .reason_codes import ReasonCode
def size_position(v:PositionSizingInput)->PositionSizingDecision:
    stop=min(v.pullback_low-.2*v.atr14,v.planned_price-1.2*v.atr14); dist=v.planned_price-stop
    if dist<=0 or dist>2.5*v.atr14:return PositionSizingDecision(0,stop,dist,0,0,(ReasonCode.STOP_TOO_WIDE,))
    theo=floor((v.net_equity*.005/dist)/100)*100; weight=.15 if v.ledger is LedgerKind.CORE else .12; by_w=floor((v.net_equity*weight/v.planned_price)/100)*100; by_l=floor((v.average_turnover20*.002/v.planned_price)/100)*100; q=max(0,min(theo,by_w,by_l)); n=q*v.planned_price
    if n<5000:return PositionSizingDecision(0,stop,dist,0,0,(ReasonCode.ORDER_BELOW_MIN_NOTIONAL,))
    return PositionSizingDecision(q,stop,dist,n,q*dist)
