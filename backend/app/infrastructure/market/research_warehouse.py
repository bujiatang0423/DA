from datetime import datetime
from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    PointInTimeSnapshot,
    QualityIssue,
    QualitySeverity,
    SnapshotScope,
)
from backend.app.core.market.snapshot import assemble_snapshot
from backend.app.infrastructure.market.research_source import ResearchSource


class ResearchPointInTimeWarehouse:
    def __init__(self, sources: tuple[ResearchSource, ...]) -> None:
        self.sources = sources

    def snapshot(self, *, as_of_time: datetime, scope: SnapshotScope) -> PointInTimeSnapshot:
        issues = [
            QualityIssue(
                "RECONSTRUCTED_HISTORY",
                QualitySeverity.WARNING,
                "snapshot",
                None,
                "provider history is reconstructed research data",
            )
        ]
        batches = []
        for source in self.sources:
            try:
                batches.append(source.fetch(as_of_time=as_of_time, scope=scope))
            except Exception:
                issues.append(
                    QualityIssue(
                        "PROVIDER_UNAVAILABLE",
                        QualitySeverity.ERROR,
                        _provider_name(source),
                        None,
                        "provider is unavailable",
                    )
                )
        records = tuple(r for b in batches for r in b.records)
        lineage = tuple(x for b in batches for x in b.lineage)
        lineage_hashes = {item.source_artifact_hash for item in lineage}
        if missing_lineage := tuple(
            record.record_id
            for record in records
            if record.source_artifact_hash not in lineage_hashes
        ):
            issues.append(
                QualityIssue(
                    "LINEAGE_MISSING",
                    QualitySeverity.ERROR,
                    "lineage",
                    None,
                    f"records missing source lineage: {','.join(missing_lineage)}",
                )
            )
        present = {r.kind for r in records}
        for kind in set(scope.required_kinds) - present:
            issues.append(
                QualityIssue(
                    "REQUIRED_DATASET_MISSING",
                    QualitySeverity.ERROR,
                    kind.value,
                    None,
                    f"required dataset missing: {kind.value}",
                )
            )
        return assemble_snapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            records=records,
            lineage=lineage,
            quality_issues=tuple(issues),
        )


def _provider_name(source: ResearchSource) -> str:
    provider = source.provider
    if isinstance(provider, str):
        return provider
    return str(getattr(provider, "provider_name", type(source).__name__))
