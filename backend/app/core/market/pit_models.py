from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from collections.abc import Mapping

from backend.app.contracts.grades import DataGrade


class DataKind(StrEnum):
    SECURITY_MASTER = "security_master"
    SECURITY_STATUS = "security_status"
    TRADING_CALENDAR = "trading_calendar"
    REALTIME_QUOTE = "realtime_quote"
    DAILY_BAR_RAW = "daily_bar_raw"
    INDEX_DAILY_BAR = "index_daily_bar"
    MARKET_BREADTH = "market_breadth"
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


# These datasets have append-only SQL rows, bundle ingestion, and strict snapshot
# selection.  Real-time and LLM inputs deliberately stay out of a certified
# historical replay until they have the same persisted provenance contract.
STRICT_BACKTEST_DATA_KINDS = (
    DataKind.SECURITY_MASTER,
    DataKind.SECURITY_STATUS,
    DataKind.TRADING_CALENDAR,
    DataKind.DAILY_BAR_RAW,
    DataKind.INDEX_DAILY_BAR,
    DataKind.MARKET_BREADTH,
    DataKind.CORPORATE_ACTION,
    DataKind.ADJUSTMENT_FACTOR,
    DataKind.INDUSTRY_MEMBERSHIP,
    DataKind.THEME_MEMBERSHIP,
    DataKind.FINANCIAL_DISCLOSURE,
    DataKind.FINANCIAL_FACT,
    DataKind.POLICY_DOCUMENT,
    DataKind.FEE_SCHEDULE,
)


@dataclass(frozen=True)
class SnapshotScope:
    security_ids: tuple[str, ...] = ()
    required_kinds: tuple[DataKind, ...] = ()
    history_start: datetime | None = None
    market_id: str = "CN_A"
    universe_id: str = "ALL_A"

    @classmethod
    def candidate_recommendation(cls) -> SnapshotScope:
        return cls(required_kinds=tuple(DataKind))

    @classmethod
    def holding_analysis(cls, security_ids: tuple[str, ...]) -> SnapshotScope:
        return cls(
            security_ids,
            (
                DataKind.SECURITY_MASTER,
                DataKind.DAILY_BAR_RAW,
                DataKind.INDEX_DAILY_BAR,
                DataKind.MARKET_BREADTH,
                DataKind.FINANCIAL_DISCLOSURE,
                DataKind.FINANCIAL_FACT,
                DataKind.POLICY_DOCUMENT,
                DataKind.LLM_FACTOR,
            ),
        )

    @classmethod
    def backtest(cls, security_ids: tuple[str, ...], history_start: datetime) -> SnapshotScope:
        return cls(security_ids, STRICT_BACKTEST_DATA_KINDS, history_start)


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
