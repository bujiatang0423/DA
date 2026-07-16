from datetime import datetime
from typing import Protocol
from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope


class PointInTimeWarehouse(Protocol):
    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot: ...
