from datetime import datetime, UTC
from decimal import Decimal

import pytest

from typing import Any
from backend.app.core.portfolio.models import CorrectionSnapshot, ManualFillCommand
from backend.app.core.portfolio.writer import AuditedPortfolioWriter


class Store:
    def __init__(self) -> None:
        self.events = []

    def append(self, *, event: Any, payload: Any, expected_version: int) -> Any:  # noqa: ANN401
        if expected_version != 3:
            raise RuntimeError("version conflict")
        self.events.append(event)
        return payload


def test_writer_records_expected_version_and_audit_hash() -> None:
    store = Store()
    cmd = ManualFillCommand("p", "AAA", "buy", 10, Decimal("10"), Decimal("1"), datetime.now(UTC), None)
    result = AuditedPortfolioWriter(store).record_manual_fill(cmd, expected_version=3)
    assert result == cmd and store.events[0].event_type == "manual_fill"
    assert len(store.events[0].payload_hash) == 64


def test_writer_propagates_optimistic_conflict_and_requires_reason() -> None:
    store = Store()
    cmd = ManualFillCommand("p", "AAA", "buy", 1, Decimal("1"), Decimal("0"), datetime.now(UTC), None)
    with pytest.raises(RuntimeError, match="version conflict"):
        AuditedPortfolioWriter(store).record_manual_fill(cmd, expected_version=2)
    snapshot = CorrectionSnapshot("p", datetime.now(UTC), Decimal("1"), Decimal("1"), ())
    with pytest.raises(ValueError, match="reason"):
        AuditedPortfolioWriter(store).replace_positions_for_correction(snapshot, 3, " ")
