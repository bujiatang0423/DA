from dataclasses import dataclass
from decimal import Decimal

from backend.app.contracts.holdings import (
    HoldingAnalysisRequest,
    HoldingAnalysisResponse,
    HoldingRisk,
)
from backend.app.ports.portfolio import PortfolioReader
from .models import PortfolioSnapshot


@dataclass(frozen=True)
class HoldingAnalysisService:
    reader: PortfolioReader

    def analyze(self, request: HoldingAnalysisRequest) -> HoldingAnalysisResponse:
        snapshot: PortfolioSnapshot = self.reader.snapshot(
            portfolio_id=request.portfolio_id, as_of_time=request.as_of_time
        )
        risks: list[HoldingRisk] = []
        gross = Decimal("0")
        for position in snapshot.positions:
            price = request.prices.get(position.security_id)
            value = (price * position.quantity) if price is not None else Decimal("0")
            gross += value
            pnl = (price - position.average_cost) * position.quantity if price is not None else None
            ret = (
                (price / position.average_cost - Decimal("1"))
                if price is not None and position.average_cost > 0
                else None
            )
            peak = position.highest_close
            drawdown = (
                (peak - price) / peak
                if peak is not None and price is not None and peak > 0
                else None
            )
            stop = position.effective_stop
            if stop is None and peak is not None:
                atr = request.atr14.get(position.security_id)
                if atr is not None and atr > 0:
                    stop = peak - Decimal("2") * atr
            breached = stop is not None and price is not None and price <= stop
            reasons: list[str] = []
            if position.origin.value == "legacy_opening_balance":
                reasons.append("LEGACY_OPENING_BALANCE")
            if breached:
                reasons.append("STOP_BREACHED")
            if drawdown is not None and drawdown >= Decimal("0.15"):
                reasons.append("DRAWDOWN_OVER_15PCT")
            status = "stop_breached" if breached else ("drawdown_warning" if reasons else "ok")
            risks.append(
                HoldingRisk(
                    security_id=position.security_id,
                    origin=position.origin.value,
                    strategy_book=position.strategy_book.value if position.strategy_book else None,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    last_price=price,
                    market_value=value,
                    unrealized_pnl=pnl,
                    unrealized_return=ret,
                    highest_close=peak,
                    drawdown_from_high=drawdown,
                    effective_stop=stop,
                    stop_breached=breached,
                    risk_status=status,
                    reasons=reasons,
                )
            )
        exposure = gross / snapshot.equity if snapshot.equity > 0 else Decimal("0")
        warnings: list[str] = []
        if exposure > request.market_max_exposure:
            warnings.append("EXPOSURE_OVER_MARKET_LIMIT")
        if request.portfolio_drawdown >= Decimal("0.06"):
            warnings.append("PORTFOLIO_WEEKLY_DRAWDOWN_TRIGGER")
        if request.portfolio_drawdown >= Decimal("0.10"):
            warnings.append("PORTFOLIO_MONTHLY_DRAWDOWN_TRIGGER")
        if any(item.stop_breached for item in risks):
            warnings.append("RISK_REDUCTION_REQUIRED")
        return HoldingAnalysisResponse(
            portfolio_id=snapshot.portfolio_id,
            as_of_time=snapshot.as_of_time,
            equity=snapshot.equity,
            gross_exposure=gross,
            exposure_ratio=exposure,
            market_max_exposure=request.market_max_exposure,
            portfolio_drawdown=request.portfolio_drawdown,
            risks=risks,
            warnings=warnings,
        )
