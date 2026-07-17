from __future__ import annotations
from collections.abc import Callable, Sequence
import builtins
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.app.contracts.common import ErrorResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from backend.app.contracts.runs import Page, RunDetail, RunKind, RunLinks, RunRef, RunStatus
from backend.app.features.runs.module import build_runs_feature
from backend.app.features.runs.service import RunsService
from backend.app.features.candidates.module import build_candidate_feature
from backend.app.features.holdings.module import build_holdings_feature
from backend.app.features.backtests.module import build_backtests_feature
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate


class _MemoryRuns:
    def __init__(self) -> None:
        self._rows: dict[str, RunDetail] = {}
        self._idempotency: dict[tuple[RunKind, str], str] = {}

    def list(self, cursor: str | None = None, limit: int = 50) -> Page[RunDetail]:
        return Page(items=builtins.list(self._rows.values())[:limit], next_cursor=None)

    def get(self, run_id: str) -> RunDetail:
        run_id = str(run_id)
        if run_id not in self._rows:
            raise KeyError(run_id)
        return self._rows[run_id]

    def artifacts(self, run_id: str) -> list[dict[str, object]]:
        run_id = str(run_id)
        self.get(run_id)
        return []

    def submit(
        self,
        kind: RunKind,
        payload: dict[str, object],
        idempotency_key: str | None,
        submitted_at: datetime,
    ) -> RunRef:
        from uuid import uuid4

        run_id = str(uuid4())
        if idempotency_key and (kind, idempotency_key) in self._idempotency:
            return self._rows[self._idempotency[(kind, idempotency_key)]].model_copy()
        ref = RunRef(
            run_id=run_id,
            kind=kind,
            status=RunStatus.QUEUED,
            submitted_at=submitted_at,
            links=RunLinks(
                self=f"/api/v1/runs/{run_id}", artifacts=f"/api/v1/runs/{run_id}/artifacts"
            ),
        )
        self._rows[run_id] = RunDetail(**ref.model_dump())
        if idempotency_key:
            self._idempotency[(kind, idempotency_key)] = run_id
        return ref


class _EmptyPortfolioReader:
    def snapshot(self, *, portfolio_id: str, as_of_time: datetime) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            portfolio_id=portfolio_id,
            as_of_time=as_of_time,
            version=0,
            cash=Decimal("0"),
            equity=Decimal("0"),
            lots=(),
        )


from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.bootstrap.settings import Settings


def create_app(
    features: Sequence[FeatureModule],
    settings: Settings | None = None,
    ready_probe: Callable[[], object] | None = None,
    token_validator: Callable[[str], bool] | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    if "*" in resolved.allowed_origins:
        raise ValueError("wildcard CORS origin is not allowed")
    app = FastAPI(title="DA Platform API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID", "Authorization"],
    )

    async def authenticate(request: Request) -> None:
        token = request.headers.get("authorization", "")
        valid = (
            token.startswith("Bearer ")
            and token_validator is not None
            and token_validator(token[7:])
        )
        if resolved.authentication_enabled and not valid:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="authentication required")

    @app.middleware("http")
    async def request_id(request: Request, call_next: object) -> object:
        value = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = value
        response = await call_next(request)
        response.headers["x-request-id"] = value
        return response

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "code": "NOT_FOUND",
                "message": "resource not found",
                "request_id": request.state.request_id,
                "details": {},
            },
        )

    @app.exception_handler(ConcurrentPortfolioUpdate)
    async def concurrent_update(request: Request, exc: ConcurrentPortfolioUpdate) -> JSONResponse:
        body = ErrorResponse(
            code="CONCURRENT_PORTFOLIO_UPDATE",
            message="portfolio changed; reload before saving",
            request_id=request.state.request_id,
            details={"reason": str(exc)},
        )
        return JSONResponse(status_code=409, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(error.get("loc", ())), "type": error.get("type", "validation_error")}
            for error in exc.errors()
        ]
        body = ErrorResponse(
            code="VALIDATION_ERROR",
            message="request validation failed",
            request_id=request.state.request_id,
            details={"errors": errors},
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "NOT_FOUND",
                    "message": "resource not found",
                    "request_id": request.state.request_id,
                    "details": {},
                },
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "request_id": request.state.request_id,
                "details": {},
            },
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        body = ErrorResponse(
            code="INTERNAL_ERROR",
            message="internal server error",
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    api = APIRouter(prefix="/api/v1")

    @api.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/health/ready")
    def ready() -> dict[str, str]:
        if ready_probe is not None:
            ready_probe()
        return {"status": "ok"}

    if not features:

        @api.get("/runs/{run_id}")
        def unavailable_run(run_id: str) -> object:
            raise KeyError(run_id)

    for feature in features:
        api.include_router(feature.router, dependencies=[Depends(authenticate)])
    app.include_router(api)
    return app


def build_application() -> FastAPI:
    settings = Settings()
    from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
    from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
    from backend.app.infrastructure.persistence.portfolio_maintenance import (
        SqlPortfolioMaintenanceService,
    )

    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    runs_service = RunsService(sessions)
    return create_app(
        (
            build_runs_feature(runs_service),
            build_candidate_feature(runs_service.submit),
            build_holdings_feature(
                SqlPortfolioReader(sessions), SqlPortfolioMaintenanceService(sessions)
            ),
            build_backtests_feature(runs_service.submit),
        )
    )  # type: ignore[arg-type]
