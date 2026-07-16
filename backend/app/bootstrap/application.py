from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from backend.app.contracts.runs import Page, RunDetail, RunKind, RunLinks, RunRef, RunStatus
from backend.app.features.runs.module import build_runs_feature


class _MemoryRuns:
    def __init__(self) -> None:
        self._rows: dict[str, RunDetail] = {}

    def list(self, cursor: str | None = None, limit: int = 50) -> Page[RunDetail]:
        return Page(items=list(self._rows.values())[:limit], next_cursor=None)

    def get(self, run_id: str) -> RunDetail:
        if run_id not in self._rows:
            raise KeyError(run_id)
        return self._rows[run_id]

    def artifacts(self, run_id: str) -> list[dict[str, object]]:
        self.get(run_id)
        return []

    def submit(self, kind: RunKind, payload: dict[str, object], idempotency_key: str | None,
               submitted_at: datetime) -> RunRef:
        from uuid import uuid4
        run_id = str(uuid4())
        ref = RunRef(run_id=run_id, kind=kind, status=RunStatus.QUEUED,
                     submitted_at=submitted_at, links=RunLinks(self=f"/api/v1/runs/{run_id}"))
        self._rows[run_id] = RunDetail(**ref.model_dump())
        return ref

from backend.app.bootstrap.feature_registry import FeatureModule
from backend.app.bootstrap.settings import Settings


def create_app(features: Sequence[FeatureModule], settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="DA Platform API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=list(resolved.allowed_origins),
                      allow_credentials=False, allow_methods=["*"],
                      allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID", "Authorization"])

    @app.middleware("http")
    async def request_id(request: Request, call_next: object) -> object:
        value = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = value
        response = await call_next(request)
        response.headers["x-request-id"] = value
        return response

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "resource not found", "request_id": request.state.request_id, "details": {}})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "resource not found", "request_id": request.state.request_id, "details": {}})
        return JSONResponse(status_code=exc.status_code, content={"code": "HTTP_ERROR", "message": str(exc.detail), "request_id": request.state.request_id, "details": {}})

    api = APIRouter(prefix="/api/v1")

    @api.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/health/ready")
    def ready() -> dict[str, str]:
        return {"status": "ok"}

    if not features:
        @api.get("/runs/{run_id}")
        def unavailable_run(run_id: str) -> object:
            raise KeyError(run_id)

    for feature in features:
        api.include_router(feature.router)
    app.include_router(api)
    return app


def build_application() -> FastAPI:
    memory = _MemoryRuns()
    return create_app((build_runs_feature(memory),))  # type: ignore[arg-type]
