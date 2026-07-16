from dataclasses import dataclass
from fastapi import APIRouter
from backend.app.contracts.runs import RunKind
from backend.app.infrastructure.tasks.handlers import JobHandler


@dataclass(frozen=True)
class FeatureModule:
    name: str
    router: APIRouter
    job_handlers: tuple[tuple[RunKind, JobHandler], ...]
