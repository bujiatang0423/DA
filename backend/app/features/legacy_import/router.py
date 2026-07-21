from fastapi import APIRouter, HTTPException

from backend.app.features.legacy_import.contracts import (
    LegacyImportConfirmRequest,
    LegacyHoldingAnalysisLinkResponse,
    LegacyImportPreviewRequest,
    LegacyImportPreviewResponse,
    LegacyImportResultResponse,
    LegacyImportSourceListResponse,
    LegacyImportSourceResponse,
)
from backend.app.features.legacy_import.inspect import LegacySourcePathError
from backend.app.features.legacy_import.web_service import (
    LegacyImportConfirmationError,
    LegacyImportResult,
    LegacyImportWebService,
)


def build_router(service: LegacyImportWebService) -> APIRouter:
    router = APIRouter(prefix="/legacy-imports", tags=["legacy-imports"])

    @router.get("/sources", response_model=LegacyImportSourceListResponse)
    def sources() -> LegacyImportSourceListResponse:
        return LegacyImportSourceListResponse(
            items=[LegacyImportSourceResponse(**source.__dict__) for source in service.sources()]
        )

    @router.post("/preview", response_model=LegacyImportPreviewResponse)
    def preview(request: LegacyImportPreviewRequest) -> LegacyImportPreviewResponse:
        try:
            value = service.preview(**request.model_dump())
        except LegacyImportConfirmationError as exc:
            raise HTTPException(
                status_code=409, detail="legacy import preview must be retried"
            ) from exc
        except LegacySourcePathError as exc:
            raise HTTPException(status_code=409, detail="legacy import source is invalid") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="legacy import source not found") from exc
        return LegacyImportPreviewResponse(
            source_id=value.source_id,
            portfolio_id=value.portfolio_id,
            effective_at=value.effective_at,
            current_position_count=value.current_position_count,
            historical_position_count=value.historical_position_count,
            source_file_count=value.source_file_count,
            quality_tags=list(value.quality_tags),
            confirmation_token=value.confirmation_token,
        )

    @router.post("/confirm", response_model=LegacyImportResultResponse)
    def confirm(request: LegacyImportConfirmRequest) -> LegacyImportResultResponse:
        try:
            value = service.confirm(**request.model_dump())
        except LegacyImportConfirmationError as exc:
            raise HTTPException(status_code=409, detail="manual confirmation is required") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="legacy import source not found") from exc
        return _result_response(value)

    @router.get("/{batch_id}", response_model=LegacyImportResultResponse)
    def result(batch_id: str) -> LegacyImportResultResponse:
        try:
            return _result_response(service.result(batch_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="legacy import batch not found") from exc

    return router


def _result_response(result: LegacyImportResult) -> LegacyImportResultResponse:
    if result.holding_analysis is None:
        raise RuntimeError("legacy import result is missing its manual analysis link")
    return LegacyImportResultResponse(
        batch_id=result.batch_id,
        portfolio_id=result.portfolio_id,
        effective_at=result.effective_at,
        manifest_sha256=result.manifest_sha256,
        raw_file_count=result.raw_file_count,
        opening_position_count=result.opening_position_count,
        historical_snapshot_count=result.historical_snapshot_count,
        idempotent=result.idempotent,
        holding_analysis=LegacyHoldingAnalysisLinkResponse(
            **result.holding_analysis.__dict__
        ),
    )
