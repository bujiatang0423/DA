from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.contracts.portfolio import PortfolioMaintenanceRequest, PortfolioPositionInput
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.persistence.portfolio_maintenance import (
    SqlPortfolioMaintenanceService,
)
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioAuditEventRow,
    PortfolioLotProjectionRow,
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


def _service() -> SqlPortfolioMaintenanceService:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            PortfolioVersionRow.__table__,
            PortfolioSnapshotProjectionRow.__table__,
            PortfolioLotProjectionRow.__table__,
            PortfolioAuditEventRow.__table__,
        ],
    )
    return SqlPortfolioMaintenanceService(sessionmaker(bind=engine, expire_on_commit=False))


def _request(version: int = 0) -> PortfolioMaintenanceRequest:
    return PortfolioMaintenanceRequest(
        portfolio_id="p1",
        as_of_time=datetime(2026, 7, 17, 9, 30, tzinfo=UTC),
        cash=Decimal("1000"),
        equity=Decimal("2000"),
        expected_version=version,
        reason="人工校正当前持仓",
        positions=[
            PortfolioPositionInput(
                batch_id="lot-2026-01",
                security_id="600000",
                security_name="浦发银行",
                buy_date=date(2026, 1, 5),
                quantity=100,
                available_to_sell=88,
                average_cost=Decimal("10"),
            )
        ],
    )


def test_maintenance_writes_projection_and_audit_version() -> None:
    service = _service()
    saved = service.replace(_request())
    assert saved.version == 1
    assert saved.positions[0].security_id == "600000"
    loaded = service.get("p1", saved.as_of_time)
    assert loaded.version == 1
    assert loaded.equity == Decimal("2000")
    assert loaded.positions[0].batch_id == "lot-2026-01"
    assert loaded.positions[0].buy_date == date(2026, 1, 5)
    assert loaded.positions[0].security_name == "浦发银行"
    assert loaded.positions[0].available_to_sell == 88


def test_maintenance_rejects_stale_version() -> None:
    service = _service()
    service.replace(_request())
    with pytest.raises(ConcurrentPortfolioUpdate):
        service.replace(_request())


def test_maintenance_does_not_increment_version_for_identical_state() -> None:
    service = _service()
    first = service.replace(_request())
    second = service.replace(_request(version=first.version))

    assert first.version == 1
    assert second.version == 1
    assert second.equity == Decimal("2000")
