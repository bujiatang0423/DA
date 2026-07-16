from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal
import hashlib, json
from typing import Protocol
from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch

@dataclass(frozen=True)
class ProviderBar:
    security_id: str; trade_date: date; open: Decimal; high: Decimal; low: Decimal; close: Decimal; volume: int

class DailyBarProvider(Protocol):
    provider_name: str
    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]: ...

class ProviderResearchSource:
    def __init__(self, provider: DailyBarProvider, strategy_timezone: tzinfo) -> None:
        self.provider, self._timezone = provider, strategy_timezone
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        start = (scope.history_start or as_of_time - timedelta(days=400)).date()
        rows = tuple(b for sid in scope.security_ids for b in self.provider.daily_bars(sid, start, as_of_time.date()))
        digest = hashlib.sha256(json.dumps([b.__dict__ for b in rows], default=str, sort_keys=True).encode()).hexdigest()
        records = tuple(TemporalRecord(f"{self.provider.provider_name}:{b.security_id}:{b.trade_date}", DataKind.DAILY_BAR_RAW,
            b.security_id, datetime.combine(b.trade_date, time(15), self._timezone), as_of_time,
            datetime.combine(b.trade_date, time(15, 30), self._timezone), digest,
            {"open": str(b.open), "high": str(b.high), "low": str(b.low), "close": str(b.close), "volume": b.volume, "price_adjustment": "none"}) for b in rows)
        return ResearchBatch(records, (LineageRef(f"{self.provider.provider_name}-{digest[:16]}", self.provider.provider_name, digest),))
