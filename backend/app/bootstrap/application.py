from collections.abc import Sequence
from uuid import uuid4
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from backend.app.bootstrap.feature_registry import FeatureModule
def create_app(features: Sequence[FeatureModule]) -> FastAPI:
    app=FastAPI(title="DA Platform API",version="0.1.0")
    @app.middleware("http")
    async def request_id(request: Request, call_next: object) -> object:
        value=request.headers.get("x-request-id",str(uuid4())); request.state.request_id=value; response=await call_next(request); response.headers["x-request-id"]=value; return response
    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(404,{"code":"NOT_FOUND","message":"resource not found","request_id":request.state.request_id,"details":{}})
    api=APIRouter(prefix="/api/v1")
    @api.get("/health/live")
    def live() -> dict[str,str]: return {"status":"ok"}
    for feature in features: api.include_router(feature.router)
    app.include_router(api); return app
def build_application() -> FastAPI: return create_app(())
