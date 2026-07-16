from dataclasses import dataclass
from datetime import datetime, timedelta
from .models import CandidateState


@dataclass(frozen=True)
class CandidateTransition:
    state: CandidateState
    changed_at: datetime


ALLOWED = {
    CandidateState.UNSELECTED: {CandidateState.SELECTED},
    CandidateState.SELECTED: {
        CandidateState.BREAKOUT,
        CandidateState.PULLBACK,
        CandidateState.STRENGTHENED,
    },
    CandidateState.BREAKOUT: {CandidateState.PENDING_EXECUTION},
    CandidateState.PULLBACK: {CandidateState.PENDING_EXECUTION},
    CandidateState.STRENGTHENED: {CandidateState.PENDING_EXECUTION},
    CandidateState.PENDING_EXECUTION: {CandidateState.HELD},
    CandidateState.HELD: set(),
}


def transition(current: CandidateState, target: CandidateState) -> CandidateState:
    if target not in ALLOWED[current]:
        raise ValueError(f"invalid transition {current}->{target}")
    return target


def is_expired(changed_at: datetime, now: datetime, days: int = 5) -> bool:
    return now - changed_at > timedelta(days=days)
