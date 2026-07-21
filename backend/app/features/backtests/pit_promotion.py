from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.contracts.grades import DataGrade, LlmGrade


class PitPromotionError(RuntimeError):
    pass


class PitPromotionAuthorizer(Protocol):
    """Confirms that a persisted audit authorizes a particular backtest run."""

    def assert_authorized(self, *, run_id: str, audit_report_id: str) -> None: ...


@dataclass(frozen=True)
class PromotionCandidate:
    run_id: str
    current_data_grade: DataGrade
    llm_grade: LlmGrade
    audit_report_id: str
    walk_forward_complete: bool
    holdout_locked: bool
    all_manifests_within_as_of: bool
    research_gate_passed: bool
    coverage_complete: bool | None = None
    lineage_verified: bool | None = None


@dataclass(frozen=True)
class PromotionResult:
    run_id: str
    data_grade: DataGrade
    llm_grade: LlmGrade
    strategy_gate_passed: bool
    audit_report_id: str


class PitPromotionService:
    """Promote only the data grade after independent PIT evidence checks pass."""

    def __init__(self, authorizer: PitPromotionAuthorizer) -> None:
        self._authorizer = authorizer

    def promote(self, candidate: PromotionCandidate) -> PromotionResult:
        if candidate.current_data_grade is not DataGrade.RESEARCH:
            raise PitPromotionError("only research results can be promoted")
        self._authorizer.assert_authorized(
            run_id=candidate.run_id,
            audit_report_id=candidate.audit_report_id,
        )
        if not candidate.walk_forward_complete:
            raise PitPromotionError("walk-forward incomplete")
        if not candidate.holdout_locked:
            raise PitPromotionError("final holdout is not locked")
        if not candidate.all_manifests_within_as_of:
            raise PitPromotionError("manifest contains future input")
        if candidate.coverage_complete is not True:
            raise PitPromotionError("PIT coverage is incomplete")
        if candidate.lineage_verified is not True:
            raise PitPromotionError("PIT lineage is unverified")
        return PromotionResult(
            run_id=candidate.run_id,
            data_grade=DataGrade.PIT_VERIFIED,
            llm_grade=candidate.llm_grade,
            strategy_gate_passed=candidate.research_gate_passed,
            audit_report_id=candidate.audit_report_id,
        )
