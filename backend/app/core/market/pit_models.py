from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from backend.app.contracts.grades import DataGrade


class DataKind(StrEnum):
    SECURITY_MASTER = "security_master"
    SECURITY_STATUS = "security_status"
    TRADING_CALENDAR = "trading_calendar"
    REALTIME_QUOTE = "realtime_quote"
    DAILY_BAR_RAW = "daily_bar_raw"
    INDEX_DAILY_BAR = "index_daily_bar"
    CORPORATE_ACTION = "corporate_action"
    ADJUSTMENT_FACTOR = "adjustment_factor"
    INDUSTRY_MEMBERSHIP = "industry_membership"
    THEME_MEMBERSHIP = "theme_membership"
    FINANCIAL_DISCLOSURE = "financial_disclosure"
    FINANCIAL_FACT = "financial_fact"
    POLICY_DOCUMENT = "policy_document"
    LLM_FACTOR = "llm_factor"
    FEE_SCHEDULE = "fee_schedule"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class SnapshotScope:
    security_ids: tuple[str, ...] = ()
    required_kinds: tuple[DataKind, ...] = ()
    history_start: datetime | None = None

    @classmethod
    def candidate_recommendation(cls) -> "SnapshotScope":
        return cls(required_kinds=tuple(DataKind))

    @classmethod
    def holding_analysis(cls, security_ids: tuple[str, ...]) -> "SnapshotScope":
        return cls(security_ids, cls.candidate_recommendation().required_kinds)

    @classmethod
    def backtest(cls, security_ids: tuple[str, ...], history_start: datetime) -> "SnapshotScope":
        return cls(security_ids, cls.candidate_recommendation().required_kinds, history_start)


@dataclass(frozen=True)
class TemporalRecord:
    record_id: str
    kind: DataKind
    entity_id: str
    event_time: datetime
    observed_at: datetime
    available_at: datetime
    source_artifact_hash: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class LineageRef:
    batch_id: str
    provider: str
    source_artifact_hash: str


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: QualitySeverity
    dataset: str
    entity_id: str | None
    detail: str


@dataclass(frozen=True)
class SnapshotQuality:
    issues: tuple[QualityIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(i.severity is QualitySeverity.ERROR for i in self.issues)


@dataclass(frozen=True)
class SecurityObservation:
    security_id: str
    records: tuple[TemporalRecord, ...]

    def records_of(self, kind: DataKind) -> tuple[TemporalRecord, ...]:
        return tuple(r for r in self.records if r.kind is kind)


@dataclass(frozen=True)
class PointInTimeSnapshot:
    as_of_time: datetime
    scope: SnapshotScope
    data_grade: DataGrade
    market_inputs: tuple[TemporalRecord, ...]
    security_observations: tuple[SecurityObservation, ...]
    quality: SnapshotQuality
    lineage: tuple[LineageRef, ...]
    manifest_hash: str
