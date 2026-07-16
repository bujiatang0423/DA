from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
class PositionOrigin(StrEnum): LEGACY_OPENING_BALANCE='legacy_opening_balance'; RECORDED_TRADE='recorded_trade'; SIMULATED_FILL='simulated_fill'
class StrategyBook(StrEnum): CORE='core'; SWING='swing'
class FillSide(StrEnum): BUY='buy'; SELL='sell'
@dataclass(frozen=True)
class OpeningPosition: security_id:str; quantity:int; inherited_unit_cost:Decimal; effective_at:datetime; source_row_hash:str; origin:PositionOrigin=PositionOrigin.LEGACY_OPENING_BALANCE; strategy_book:StrategyBook|None=None; entry_score:Decimal|None=None; initial_risk_per_share:Decimal|None=None
@dataclass(frozen=True)
class PortfolioLot:
    lot_id:str; security_id:str; quantity:int; available_to_sell:int; average_cost:Decimal; effective_at:datetime; origin:PositionOrigin; strategy_book:StrategyBook|None; entry_score:Decimal|None; initial_risk_per_share:Decimal|None; effective_stop:Decimal|None; highest_close:Decimal|None; add_count:int
@dataclass(frozen=True)
class PortfolioPosition:
    security_id:str; strategy_book:StrategyBook|None; origin:PositionOrigin; quantity:int; available_to_sell:int; average_cost:Decimal; effective_stop:Decimal|None; highest_close:Decimal|None; entry_score:Decimal|None; initial_risk_per_share:Decimal|None; add_count:int
@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio_id:str; as_of_time:datetime; version:int; cash:Decimal; equity:Decimal; lots:tuple[PortfolioLot,...]
    @property
    def positions(self)->tuple[PortfolioPosition,...]:
        out=[]
        for sid in sorted({l.security_id for l in self.lots}):
            g=[l for l in self.lots if l.security_id==sid]; q=sum(l.quantity for l in g)
            if q: out.append(PortfolioPosition(sid,g[0].strategy_book,g[0].origin,q,sum(l.available_to_sell for l in g),sum(l.average_cost*l.quantity for l in g)/q,max((l.effective_stop for l in g if l.effective_stop),default=None),max((l.highest_close for l in g if l.highest_close),default=None),g[0].entry_score,g[0].initial_risk_per_share,max(l.add_count for l in g)))
        return tuple(out)
