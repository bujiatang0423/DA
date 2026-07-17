from datetime import datetime

from fastapi import APIRouter

from backend.app.contracts.portfolio import (
    PortfolioMaintenanceRequest,
    PortfolioMaintenanceResponse,
)
from backend.app.infrastructure.persistence.portfolio_maintenance import (
    SqlPortfolioMaintenanceService,
)


def build_maintenance_router(service: SqlPortfolioMaintenanceService) -> APIRouter:
    router = APIRouter(prefix="/maintenance", tags=["portfolio-maintenance"])

    @router.get("", response_model=PortfolioMaintenanceResponse)
    def get_maintenance(portfolio_id: str, as_of_time: datetime) -> PortfolioMaintenanceResponse:
        return service.get(portfolio_id, as_of_time)

    @router.put("", response_model=PortfolioMaintenanceResponse)
    def replace_maintenance(request: PortfolioMaintenanceRequest) -> PortfolioMaintenanceResponse:
        return service.replace(request)

    return router
