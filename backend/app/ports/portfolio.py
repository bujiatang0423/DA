from datetime import datetime
from typing import Protocol
from backend.app.core.portfolio.models import PortfolioSnapshot, OpeningPosition
class ConcurrentPortfolioUpdate(RuntimeError): pass
class PortfolioReader(Protocol):
    def snapshot(self, *, portfolio_id:str, as_of_time:datetime)->PortfolioSnapshot: ...
class OpeningBalanceWriter(Protocol):
    def apply(self, *, batch_id:str, portfolio_id:str, effective_at:datetime, positions:tuple[OpeningPosition,...])->None: ...
