from datetime import datetime

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
)
from backend.app.core.market.snapshot import assemble_snapshot


class UnavailableResearchWarehouse:
    """Explicit fail-closed warehouse used until all providers are configured."""

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        missing = tuple(
            QualityIssue(
                "REQUIRED_DATASET_MISSING",
                QualitySeverity.ERROR,
                kind.value,
                None,
                "candidate provider is not configured",
            )
            for kind in scope.required_kinds
        )
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=(),
            lineage=(),
            quality_issues=missing,
        )
