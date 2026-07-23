"""Best-effort asynchronous loader for locally refreshed daily bars."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from collections.abc import Callable

from sqlalchemy.orm import Session

from backend.app.infrastructure.persistence.strict_pit_rows import DailyBarRawRow


class LocalMarketDatabaseRefresher:
    """Copy refreshed DA fixture bars into the PIT database without blocking saves."""

    def __init__(self, sessions: Callable[[], Session], fixture: Path) -> None:
        self._sessions = sessions
        self._fixture = fixture

    def __call__(self, symbols: tuple[str, ...], available_at: datetime) -> None:
        if not self._fixture.exists():
            return
        payload = json.loads(self._fixture.read_text(encoding="utf-8"))
        artifact_hash = sha256(self._fixture.read_bytes()).hexdigest()
        with self._sessions.begin() as session:
            for symbol in symbols:
                for bar in (payload.get(symbol) or {}).get("bars", []):
                    trade_date = datetime.strptime(str(bar["trade_date"]), "%Y%m%d").date()
                    record_id = f"local-refresh:{symbol}:{trade_date}:{artifact_hash[:16]}"
                    session.merge(
                        DailyBarRawRow(
                            id=record_id,
                            source_record_id=record_id,
                            security_id=symbol,
                            trade_date=trade_date,
                            open=bar["open"],
                            high=bar["high"],
                            low=bar["low"],
                            close=bar["close"],
                            volume=int(bar.get("volume", 0)),
                            amount=bar.get("amount", 0),
                            available_at=available_at,
                            source_artifact_hash=artifact_hash,
                        )
                    )
