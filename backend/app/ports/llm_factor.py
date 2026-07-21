from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial


@dataclass(frozen=True)
class StructuredLlmFactor:
    as_of_time: datetime
    security_id: str
    model_id: str
    prompt_hash: str
    input_hash: str
    output_hash: str
    payload: dict[str, object]


@runtime_checkable
class LlmFactorPort(Protocol):
    def extract(
        self,
        *,
        as_of_time: datetime,
        security_id: str,
        policy_materials: tuple[PolicyMaterial, ...],
        financial_materials: tuple[FinancialMaterial, ...],
    ) -> StructuredLlmFactor: ...
