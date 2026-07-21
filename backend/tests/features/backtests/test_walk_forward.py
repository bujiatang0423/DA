from datetime import date

import pytest

from backend.app.features.backtests.walk_forward import WalkForwardPlan, WalkForwardWindow


def test_rolling_uses_calendar_year_windows_and_locks_one_year_holdout() -> None:
    plan = WalkForwardPlan.rolling(date(2020, 1, 1), date(2026, 12, 31))

    assert plan.holdout.start == date(2026, 1, 1)
    assert plan.holdout.end == date(2026, 12, 31)
    assert plan.windows == (
        WalkForwardWindow(date(2020, 1, 1), date(2022, 12, 31), date(2023, 1, 1), date(2023, 12, 31)),
        WalkForwardWindow(date(2021, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 12, 31)),
        WalkForwardWindow(date(2022, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
    )


@pytest.mark.parametrize(
    ("start", "end", "holdout_months"),
    (
        (date(2027, 1, 1), date(2026, 12, 31), 12),
        (date(2025, 1, 1), date(2026, 12, 31), 12),
        (date(2020, 1, 1), date(2026, 12, 31), 0),
    ),
)
def test_rolling_rejects_invalid_or_too_short_ranges(
    start: date,
    end: date,
    holdout_months: int,
) -> None:
    with pytest.raises(ValueError):
        WalkForwardPlan.rolling(start, end, holdout_months)
