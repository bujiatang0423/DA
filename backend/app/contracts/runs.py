from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar, Literal
from pydantic import Field, field_validator
from .common import ContractModel, require_aware

T = TypeVar("T")


class ErrorResponse(ContractModel):
    code: str
    message: str
    request_id: str
    details: dict[str, object] = Field(default_factory=dict)


class Page(ContractModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class RunKind(StrEnum):
    CANDIDATE_RECOMMENDATION = "candidate_recommendation"
    HOLDING_ANALYSIS = "holding_analysis"
    BACKTEST = "backtest"
    LEGACY_IMPORT = "legacy_import"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunLinks(ContractModel):
    self: str
    artifacts: str | None = None
    result: str | None = None


class RunRef(ContractModel):
    run_id: str = Field(min_length=1, max_length=64)
    kind: RunKind
    status: RunStatus
    submitted_at: datetime
    links: RunLinks
    _aware = field_validator("submitted_at")(require_aware)
    auto_trade_enabled: Literal[False] = False
    human_confirm_required: Literal[True] = True


class RunDetail(RunRef):
    stage: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    heartbeat_at: datetime | None = None
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, min_length=1, max_length=64)
