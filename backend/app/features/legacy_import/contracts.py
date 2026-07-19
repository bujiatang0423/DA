from datetime import datetime

from pydantic import BaseModel, Field


class LegacyImportSourceResponse(BaseModel):
    source_id: str
    label: str


class LegacyImportSourceListResponse(BaseModel):
    items: list[LegacyImportSourceResponse]


class LegacyImportPreviewRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=128)
    portfolio_id: str = Field(min_length=1, max_length=64)
    effective_at: datetime


class LegacyImportPreviewResponse(BaseModel):
    source_id: str
    portfolio_id: str
    effective_at: datetime
    current_position_count: int
    historical_position_count: int
    source_file_count: int
    quality_tags: list[str]
    confirmation_token: str


class LegacyImportConfirmRequest(LegacyImportPreviewRequest):
    confirmation_token: str = Field(min_length=20, max_length=256)


class LegacyImportResultResponse(BaseModel):
    batch_id: str
    manifest_sha256: str
    raw_file_count: int
    opening_position_count: int
    historical_snapshot_count: int
    idempotent: bool
