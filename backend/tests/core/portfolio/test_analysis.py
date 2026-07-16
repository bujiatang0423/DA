from datetime import UTC, datetime
from decimal import Decimal

from backend.app.contracts.holdings import HoldingAnalysisRequest
from backend.app.core.portfolio.analysis import HoldingAnalysisService
from backend.app.core.portfolio.models import (
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
)


class Reader:
    def __init__(self, snapshot: PortfolioSnapshot) -> None:
        self.snapshot_value = snapshot

    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        assert portfolio_id == self.snapshot_value.portfolio_id
        return self.snapshot_value


def test_analysis_flags_legacy_stop_and_drawdown() -> None:
    as_of = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "p1",
        as_of,
        1,
        Decimal("1000"),
        Decimal("10000"),
        (
            PortfolioLot(
                "lot1",
                "600000",
                100,
                100,
                Decimal("10"),
                as_of,
                PositionOrigin.LEGACY_OPENING_BALANCE,
                None,
                None,
                None,
                None,
                Decimal("12"),
                0,
            ),
        ),
    )
    result = HoldingAnalysisService(Reader(snapshot)).analyze(
        HoldingAnalysisRequest(
            portfolio_id="p1",
            as_of_time=as_of,
            prices={"600000": Decimal("9")},
            atr14={"600000": Decimal("1")},
            portfolio_drawdown=Decimal("0.06"),
        )
    )
    risk = result.risks[0]
    assert risk.origin == "legacy_opening_balance"
    assert risk.stop_breached
    assert risk.drawdown_from_high == Decimal("0.25")
    assert "RISK_REDUCTION_REQUIRED" in result.warnings
    assert "PORTFOLIO_WEEKLY_DRAWDOWN_TRIGGER" in result.warnings


def test_analysis_uses_atr_stop_when_no_persisted_stop() -> None:
    as_of = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "p1",
        as_of,
        1,
        Decimal("1000"),
        Decimal("10000"),
        (
            PortfolioLot(
                "lot1",
                "000001",
                100,
                100,
                Decimal("10"),
                as_of,
                PositionOrigin.SIMULATED_FILL,
                None,
                None,
                None,
                None,
                Decimal("12"),
                0,
            ),
        ),
    )
    result = HoldingAnalysisService(Reader(snapshot)).analyze(
        HoldingAnalysisRequest(
            portfolio_id="p1",
            as_of_time=as_of,
            prices={"000001": Decimal("11")},
            atr14={"000001": Decimal("1")},
        )
    )
    assert result.risks[0].effective_stop == Decimal("10")
    assert not result.risks[0].stop_breached
