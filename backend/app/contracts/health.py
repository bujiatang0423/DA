from typing import Literal

from backend.app.contracts.common import ContractModel


class ReadinessComponents(ContractModel):
    database: Literal["ready", "unavailable", "unknown"]
    worker: Literal["ready", "missing", "stale", "unknown"]


class ReadinessResponse(ContractModel):
    status: Literal["ready", "not_ready"]
    components: ReadinessComponents
