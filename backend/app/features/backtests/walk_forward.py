from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


class HoldoutViolation(ValueError):
    pass


@dataclass(frozen=True)
class WalkForwardWindow:
    development_start: date
    development_end: date
    validation_start: date
    validation_end: date


@dataclass(frozen=True)
class HoldoutLock:
    start: date
    end: date

    def assert_not_touched(self, start: date, end: date) -> None:
        if start <= self.end and end >= self.start:
            raise HoldoutViolation("final holdout is locked")


@dataclass(frozen=True)
class WalkForwardPlan:
    windows: tuple[WalkForwardWindow, ...]
    holdout: HoldoutLock

    @classmethod
    def rolling(cls, start: date, end: date, holdout_months: int = 12) -> WalkForwardPlan:
        if start > end:
            raise ValueError("walk-forward start must not be after end")
        if holdout_months <= 0:
            raise ValueError("holdout_months must be positive")
        holdout_start = _shift_months(end, -holdout_months) + timedelta(days=1)
        if holdout_start <= start:
            raise ValueError("walk-forward range is shorter than the holdout")
        holdout = HoldoutLock(holdout_start, end)
        development_end = holdout_start - timedelta(days=1)
        windows: list[WalkForwardWindow] = []
        cursor = start
        while _shift_years(cursor, 3) - timedelta(days=1) <= development_end:
            dev_end = _shift_years(cursor, 3) - timedelta(days=1)
            val_end = min(_shift_years(dev_end + timedelta(days=1), 1) - timedelta(days=1), development_end)
            if dev_end < development_end:
                windows.append(
                    WalkForwardWindow(cursor, dev_end, dev_end + timedelta(days=1), val_end)
                )
            cursor = _shift_years(cursor, 1)
        if not windows:
            raise ValueError("walk-forward range has no complete development window")
        return cls(tuple(windows), holdout)


def _shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # Preserve a valid calendar date for February 29 anniversaries.
        return value.replace(year=value.year + years, day=28)


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days
