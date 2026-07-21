from __future__ import annotations

import pytest

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.backtests.pit_promotion import (
    PitPromotionError,
    PitPromotionService,
    PromotionCandidate,
)


class AuditAuthorizer:
    def __init__(self, authorized: bool) -> None:
        self._authorized = authorized
        self.calls: list[tuple[str, str]] = []

    def assert_authorized(self, *, run_id: str, audit_report_id: str) -> None:
        self.calls.append((run_id, audit_report_id))
        if not self._authorized:
            raise PitPromotionError("audit did not pass")


def candidate(**changes: object) -> PromotionCandidate:
    values: dict[str, object] = {
        "run_id": "run-1",
        "current_data_grade": DataGrade.RESEARCH,
        "llm_grade": LlmGrade.RECONSTRUCTED,
        "audit_report_id": "audit-1",
        "walk_forward_complete": True,
        "holdout_locked": True,
        "all_manifests_within_as_of": True,
        "research_gate_passed": False,
        "coverage_complete": True,
        "lineage_verified": True,
    }
    values.update(changes)
    return PromotionCandidate(**values)  # type: ignore[arg-type]


def test_profitable_run_without_audit_cannot_be_promoted() -> None:
    authorizer = AuditAuthorizer(authorized=False)

    with pytest.raises(PitPromotionError, match="audit did not pass"):
        PitPromotionService(authorizer).promote(candidate(research_gate_passed=True))

    assert authorizer.calls == [("run-1", "audit-1")]


def test_verified_data_is_independent_from_strategy_gate_and_llm_grade() -> None:
    result = PitPromotionService(AuditAuthorizer(authorized=True)).promote(candidate())

    assert result.data_grade is DataGrade.PIT_VERIFIED
    assert result.strategy_gate_passed is False
    assert result.llm_grade is LlmGrade.RECONSTRUCTED


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("walk_forward_complete", "walk-forward incomplete"),
        ("holdout_locked", "final holdout is not locked"),
        ("all_manifests_within_as_of", "manifest contains future input"),
        ("coverage_complete", "PIT coverage is incomplete"),
        ("lineage_verified", "PIT lineage is unverified"),
    ],
)
def test_promotion_requires_every_non_yield_pit_gate(field: str, message: str) -> None:
    with pytest.raises(PitPromotionError, match=message):
        PitPromotionService(AuditAuthorizer(authorized=True)).promote(candidate(**{field: False}))


def test_promotion_is_one_way_from_research_only() -> None:
    with pytest.raises(PitPromotionError, match="only research results"):
        PitPromotionService(AuditAuthorizer(authorized=True)).promote(
            candidate(current_data_grade=DataGrade.PIT_VERIFIED)
        )


def test_promotion_fails_closed_when_new_pit_evidence_is_unspecified() -> None:
    values = candidate().__dict__
    values["coverage_complete"] = None

    with pytest.raises(PitPromotionError, match="PIT coverage is incomplete"):
        PitPromotionService(AuditAuthorizer(authorized=True)).promote(
            PromotionCandidate(**values)
        )
