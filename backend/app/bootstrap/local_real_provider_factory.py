"""Local real-data provider factory; never loads fixtures."""
from __future__ import annotations
from datetime import datetime
import os
import akshare
from backend.app.bootstrap.composition import ProductionResearchProviders
from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.llm.deepseek_provider import DeepSeekFactorProvider
from backend.app.infrastructure.market.akshare_research_provider import AkShareResearchProvider

class LocalPolicy:
    def materials(self, *, as_of_time: datetime) -> tuple[object, ...]:
        return ()

def build(settings: Settings) -> ProductionResearchProviders:
    del settings
    return ProductionResearchProviders(
        AkShareResearchProvider(akshare),
        LocalPolicy(),
        DeepSeekFactorProvider(api_key=os.getenv("DEEPSEEK_API_KEY")),
    )
