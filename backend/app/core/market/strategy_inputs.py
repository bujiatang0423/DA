from dataclasses import fields
from datetime import datetime
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import (StrategyEvaluationRequest, MarketRegimeInput,
    PortfolioView, SecurityEvaluationInput, MarketState, LedgerKind, FinancialLight)
from backend.app.contracts.strategy import AsOf, StrategyVersion

class StrategyInputError(ValueError): pass

class StrategyInputBuilder:
    def build(self, *, snapshot:PointInTimeSnapshot, portfolio:PortfolioSnapshot,
              strategy_version:str)->StrategyEvaluationRequest:
        if snapshot.quality.has_errors: raise StrategyInputError('snapshot quality contains errors')
        if not any(r.kind is DataKind.TRADING_CALENDAR for r in snapshot.market_inputs):
            raise StrategyInputError('market breadth missing')
        market=MarketRegimeInput(0,0,0,0,0,0,0,0,0,0,0,0,0,False,MarketState.NEUTRAL,0,False)
        pview=PortfolioView(float(portfolio.equity),0,0,len(portfolio.positions))
        securities=[]
        for obs in snapshot.security_observations:
            master=next((r.payload for r in obs.records if r.kind is DataKind.SECURITY_MASTER),{})
            securities.append(SecurityEvaluationInput(obs.security_id,str(master.get('name','')),str(master.get('industry_id','')),None,LedgerKind.CORE,(),0,0,FinancialLight.UNKNOWN,'unknown',0,0,False,False,False,False,0,0,0,0,0,0,0,0,0,0,False,False,False,False,False,False,False,False,False,None,0,False,False,False,False,False,()))
        as_of = AsOf(as_of_time=snapshot.as_of_time)
        strategy = StrategyVersion(version=strategy_version, sha256=snapshot.manifest_hash)
        return StrategyEvaluationRequest(as_of, strategy, snapshot.manifest_hash, market, pview, tuple(securities))
