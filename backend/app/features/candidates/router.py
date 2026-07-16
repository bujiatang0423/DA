from fastapi import APIRouter


def build_router() -> APIRouter:
    router = APIRouter(prefix="/candidates", tags=["candidates"])

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return router
