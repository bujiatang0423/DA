from dataclasses import asdict
from datetime import datetime, UTC
import hashlib
import json
from backend.app.core.portfolio.models import PortfolioSnapshot, PortfolioAuditEvent


class AuditedPortfolioWriter:
    def __init__(self, store: object) -> None:
        self._store = store

    def record_manual_fill(self, command: object, expected_version: int) -> PortfolioSnapshot:
        event = PortfolioAuditEvent(
            command.portfolio_id,
            "manual_fill",
            datetime.now(UTC),
            expected_version,
            "用户录入真实成交",
            _payload_hash(command),
        )
        return self._store.append(event=event, payload=command, expected_version=expected_version)

    def replace_positions_for_correction(
        self, snapshot: object, expected_version: int, reason: str
    ) -> PortfolioSnapshot:
        if not reason.strip():
            raise ValueError("correction reason is required")
        event = PortfolioAuditEvent(
            snapshot.portfolio_id,
            "position_correction",
            datetime.now(UTC),
            expected_version,
            reason.strip(),
            _payload_hash(snapshot),
        )
        return self._store.append(event=event, payload=snapshot, expected_version=expected_version)


def _payload_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(asdict(payload), sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
