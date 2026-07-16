from datetime import datetime
from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import PointInTimeSnapshot, QualityIssue, QualitySeverity, SnapshotScope
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.infrastructure.market.research_source import ResearchSource


class ResearchPointInTimeWarehouse:
    def __init__(self, sources: tuple[ResearchSource, ...]) -> None:
        self.sources = sources

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        batches = tuple(s.fetch(as_of_time=as_of_time, scope=scope) for s in self.sources)
        records = tuple(r for b in batches for r in b.records)
        lineage = tuple(x for b in batches for x in b.lineage)
        issues = [QualityIssue("RECONSTRUCTED_HISTORY", QualitySeverity.WARNING, "snapshot", None,
                               "provider history is reconstructed research data")]
        present = {r.kind for r in records}
        for kind in set(scope.required_kinds) - present:
            issues.append(QualityIssue("REQUIRED_DATASET_MISSING", QualitySeverity.ERROR,
                                       kind.value, None, f"required dataset missing: {kind.value}"))
        return assemble_snapshot(as_of_time=as_of_time, scope=scope, data_grade=DataGrade.RESEARCH,
                                 records=records, lineage=lineage, quality_issues=tuple(issues))
