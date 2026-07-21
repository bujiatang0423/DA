from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import hmac
from string import hexdigits

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.market.pit_models import SnapshotScope
from backend.app.features.backtests.pit_certificate import (
    PitCertificate,
    lineage_set_hash,
    selected_snapshot_hash,
)
from backend.app.infrastructure.market.strict_reader import SqlStrictRecordReader
from backend.app.infrastructure.persistence.strict_pit_rows import (
    PitAuditReportRow,
    PitBundleRow,
    PitCertificateRow,
)


class SqlPitCertificateAuthority:
    """Approves only persisted, passed audit reports for their actual bundle set."""

    def __init__(self, session: Session, approval_secret: str) -> None:
        self._session = session
        if not approval_secret:
            raise ValueError("PIT certificate approval secret is required")
        self._approval_secret = approval_secret.encode("utf-8")

    def approve(
        self,
        audit_report_id: str,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> None:
        report = self._session.get(PitAuditReportRow, audit_report_id)
        if report is None or not report.passed:
            raise ValueError("a passed audit report is required")
        if report.coverage_start > report.coverage_end:
            raise ValueError("audit report coverage is invalid")
        if report.market_id is None or report.universe_id is None:
            raise ValueError("audit report scope identity is required")
        if report.market_id != scope.market_id or report.universe_id != scope.universe_id:
            raise ValueError("audit report scope identity does not match certificate scope")
        if not _is_sha256(report.bundle_set_hash) or not _is_sha256(report.audit_hash):
            raise ValueError("audit report integrity hashes are invalid")
        covered_hash = bundle_set_hash_for_range(
            self._session, report.coverage_start, report.coverage_end
        )
        if report.bundle_set_hash != covered_hash:
            raise ValueError("audit report does not match the persisted bundle set")
        records, lineage, issues = SqlStrictRecordReader(self._session).read(
            as_of_time=as_of_time,
            scope=scope,
        )
        if not records or issues:
            raise ValueError("audit approval requires complete strict snapshot data")
        certified_lineage_hash = lineage_set_hash(lineage)
        certified_snapshot_hash = selected_snapshot_hash(records, lineage)
        existing = self._session.get(PitCertificateRow, audit_report_id)
        if existing is not None:
            if not self._matches_approval(existing, report):
                raise ValueError("certificate approval integrity mismatch")
            return
        approved_at = datetime.now(UTC)
        self._session.add(
            PitCertificateRow(
                audit_report_id=report.id,
                coverage_start=report.coverage_start,
                coverage_end=report.coverage_end,
                bundle_set_hash=report.bundle_set_hash,
                audit_hash=report.audit_hash,
                approval_token=self._approval_token(
                    report,
                    as_of_time,
                    scope_hash(scope),
                    certified_lineage_hash,
                    certified_snapshot_hash,
                ),
                approved_at=approved_at,
                certified_as_of=as_of_time,
                scope_hash=scope_hash(scope),
                lineage_hash=certified_lineage_hash,
                selected_snapshot_hash=certified_snapshot_hash,
            )
        )
        self._session.flush()

    def certificate_for(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
        bundle_set_hash: str,
        lineage_hash: str,
        selected_snapshot_hash: str,
    ) -> PitCertificate | None:
        statement = (
            select(PitCertificateRow, PitAuditReportRow)
            .join(PitAuditReportRow, PitCertificateRow.audit_report_id == PitAuditReportRow.id)
            .where(
                PitAuditReportRow.passed.is_(True),
                PitCertificateRow.coverage_start <= as_of_time.date(),
                PitCertificateRow.coverage_end >= as_of_time.date(),
                PitCertificateRow.bundle_set_hash == bundle_set_hash,
                PitCertificateRow.certified_as_of == as_of_time,
                PitCertificateRow.scope_hash == scope_hash(scope),
                PitCertificateRow.lineage_hash == lineage_hash,
                PitCertificateRow.selected_snapshot_hash == selected_snapshot_hash,
            )
            .order_by(PitAuditReportRow.verified_at.desc(), PitAuditReportRow.id.desc())
        )
        for certificate, report in self._session.execute(statement):
            if self._matches_approval(certificate, report):
                return PitCertificate(
                    certificate.audit_report_id,
                    certificate.coverage_start,
                    certificate.coverage_end,
                    certificate.bundle_set_hash,
                    certificate.audit_hash,
                )
        return None

    def bundle_set_hash_for(self, as_of_date: date) -> str:
        return bundle_set_hash_for(self._session, as_of_date)

    def _matches_approval(self, certificate: PitCertificateRow, report: PitAuditReportRow) -> bool:
        return _matches_report(certificate, report) and hmac.compare_digest(
            certificate.approval_token,
            self._approval_token(
                report,
                certificate.certified_as_of,
                certificate.scope_hash,
                certificate.lineage_hash,
                certificate.selected_snapshot_hash,
            ),
        )

    def _approval_token(
        self,
        report: PitAuditReportRow,
        certified_as_of: datetime,
        certified_scope_hash: str,
        certified_lineage_hash: str,
        certified_snapshot_hash: str,
    ) -> str:
        payload = "|".join(
            (
                "pit-certificate-v2",
                report.id,
                report.coverage_start.isoformat(),
                report.coverage_end.isoformat(),
                report.bundle_set_hash,
                report.audit_hash,
                str(int(certified_as_of.timestamp() * 1_000_000)),
                certified_scope_hash,
                certified_lineage_hash,
                certified_snapshot_hash,
            )
        )
        return hmac.new(self._approval_secret, payload.encode("utf-8"), sha256).hexdigest()


def bundle_set_hash_for(session: Session, as_of_date: date) -> str:
    manifests = session.scalars(
        select(PitBundleRow.manifest_sha256)
        .where(
            PitBundleRow.coverage_start <= as_of_date,
            PitBundleRow.coverage_end >= as_of_date,
        )
        .order_by(PitBundleRow.manifest_sha256)
    ).all()
    if not manifests:
        raise ValueError("no persisted PIT bundle covers the requested date")
    return sha256("|".join(manifests).encode("utf-8")).hexdigest()


def bundle_set_hash_for_range(session: Session, start: date, end: date) -> str:
    """Return the bundle-set hash only when the complete date range is covered.

    Certificates represent one immutable bundle set.  A range with a missing day
    or a changing set of manifests cannot be certified by that single hash.
    """
    if start > end:
        raise ValueError("bundle coverage start must not be after end")
    rows = session.scalars(
        select(PitBundleRow)
        .where(PitBundleRow.coverage_end >= start, PitBundleRow.coverage_start <= end)
        .order_by(PitBundleRow.coverage_start, PitBundleRow.coverage_end, PitBundleRow.id)
    ).all()
    if not rows:
        raise ValueError("no persisted PIT bundle covers the requested range")

    manifest_sets: set[tuple[str, ...]] = set()
    segment_end = start - timedelta(days=1)
    active: list[PitBundleRow] = []
    for row in rows:
        row_start = max(start, row.coverage_start)
        row_end = min(end, row.coverage_end)
        if row_start > row_end:
            continue
        if row_start > segment_end + timedelta(days=1):
            raise ValueError("persisted PIT bundle coverage has a gap")
        active.append(row)
        segment_end = max(segment_end, row_end)
        if segment_end >= end:
            break
    if segment_end < end:
        raise ValueError("persisted PIT bundle coverage has a gap")
    manifest_sets.add(tuple(sorted(item.manifest_sha256 for item in active)))
    if len(manifest_sets) != 1:
        raise ValueError("persisted PIT bundle set changes within the certified range")
    manifests = next(iter(manifest_sets))
    return sha256("|".join(manifests).encode("utf-8")).hexdigest()


def _matches_report(certificate: PitCertificateRow, report: PitAuditReportRow) -> bool:
    return (
        certificate.audit_report_id == report.id
        and certificate.coverage_start == report.coverage_start
        and certificate.coverage_end == report.coverage_end
        and certificate.bundle_set_hash == report.bundle_set_hash
        and certificate.audit_hash == report.audit_hash
    )


def scope_hash(scope: SnapshotScope) -> str:
    payload = "|".join(
        (
            ",".join(sorted(scope.security_ids)),
            ",".join(sorted(kind.value for kind in scope.required_kinds)),
            scope.history_start.isoformat() if scope.history_start is not None else "",
            scope.market_id,
            scope.universe_id,
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in hexdigits for char in value)
