from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID
from backend.app.ports.uow import PersistenceUnitOfWork


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: UUID
    run_id: UUID
    name: str
    sha256: str
    media_type: str


class ArtifactRepository(Protocol):
    def save_json(
        self, uow: PersistenceUnitOfWork, run_id: UUID, name: str, payload: object
    ) -> ArtifactRef: ...
    def open(self, run_id: UUID, artifact_id: UUID) -> BinaryIO: ...
