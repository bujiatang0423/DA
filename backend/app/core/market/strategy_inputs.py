from dataclasses import fields
from backend.app.core.market.pit_models import DataKind, PointInTimeSnapshot
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import StrategyEvaluationRequest, MarketRegimeInput, PortfolioView, SecurityEvaluationInput, MarketState, LedgerKind, FinancialLight
from backend.app.contracts.strategy import AsOf, StrategyVersion

class StrategyInputError(ValueError): pass
def moving_average(values: tuple[float, ...], window: int) -> float:
    if len(values) < window: raise StrategyInputError(f'insufficient data for MA{window}')
    return sum(values[-window:]) / window
def winsorized_percentile(values: tuple[float, ...], value: float) -> float:
    if not values: return 0.5
    return min(.99, max(.01, sum(x <= value for x in values) / len(values)))

class StrategyInputBuilder:
    def build(self, *, snapshot: PointInTimeSnapshot, portfolio: PortfolioSnapshot, strategy_version: str) -> StrategyEvaluationRequest:
        if snapshot.quality.has_errors: raise StrategyInputError('snapshot quality contains errors')
        if not any(r.kind is DataKind.TRADING_CALENDAR for r in snapshot.market_inputs): raise StrategyInputError('market breadth missing')
        market = MarketRegimeInput(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False, MarketState.NEUTRAL, 0, False)
        pview = PortfolioView(float(portfolio.equity), 0, 0, len(portfolio.positions))
        securities = []
        for obs in snapshot.security_observations:
            master = next((r.payload for r in obs.records if r.kind is DataKind.SECURITY_MASTER), {})
            complete = len(obs.records_of(DataKind.FINANCIAL_FACT)) >= 2
            values = {f.name: (False if 'bool' in str(f.type) else (None if 'None' in str(f.type) else (0.0 if 'float' in str(f.type) else 0))) for f in fields(SecurityEvaluationInput)}
            values.update({'security_id': obs.security_id, 'name': str(master.get('name', '')), 'industry': str(master.get('industry_id', '')), 'ledger': LedgerKind.CORE, 'financial_light': FinancialLight.UNKNOWN, 'policy_direction': 'unknown', 'hard_filter_passed': complete, 'quality_codes': () if complete else ('FINANCIAL_TEMPLATE_INCOMPLETE',)})
            securities.append(SecurityEvaluationInput(**values))
        return StrategyEvaluationRequest(AsOf(as_of_time=snapshot.as_of_time), StrategyVersion(version=strategy_version, sha256=snapshot.manifest_hash), snapshot.manifest_hash, market, pview, tuple(securities))
