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
        holdout_start = end - timedelta(days=holdout_months * 30)
        holdout = HoldoutLock(holdout_start, end)
        development_end = holdout_start - timedelta(days=1)
        windows: list[WalkForwardWindow] = []
        cursor = start
        while cursor + timedelta(days=365) <= development_end:
            dev_end = cursor + timedelta(days=365 * 3 - 1)
            val_end = min(dev_end + timedelta(days=365), development_end)
            if dev_end < development_end:
                windows.append(
                    WalkForwardWindow(cursor, dev_end, dev_end + timedelta(days=1), val_end)
                )
            cursor += timedelta(days=365)
        return cls(tuple(windows), holdout)
