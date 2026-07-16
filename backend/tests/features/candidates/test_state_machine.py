import pytest
from backend.app.features.candidates.models import CandidateState
from backend.app.features.candidates.state_machine import transition
def test_transition_rejects_invalid() -> None:
    assert transition(CandidateState.SELECTED,CandidateState.BREAKOUT) is CandidateState.BREAKOUT
    with pytest.raises(ValueError): transition(CandidateState.HELD,CandidateState.SELECTED)
