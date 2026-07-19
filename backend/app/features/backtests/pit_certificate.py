from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PitCertificate:
    audit_report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    audit_hash: str


class PassedAuditReport(Protocol):
    passed: bool
    report_id: str
    coverage_start: date
    coverage_end: date
    bundle_set_hash: str
    audit_hash: str


class PitAuditAuthorizer:
    def issue(self, report: PassedAuditReport) -> PitCertificate:
        if not report.passed:
            raise ValueError("failed audit cannot issue certificate")
        return PitCertificate(
            report.report_id,
            report.coverage_start,
            report.coverage_end,
            report.bundle_set_hash,
            report.audit_hash,
        )
