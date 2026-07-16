from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session, sessionmaker
from backend.app.infrastructure.persistence.artifact_paths import UnsafeArtifactPath, resolve_artifact
from backend.app.infrastructure.persistence.models import RunArtifactRow
from backend.app.ports.artifacts import ArtifactRef
from backend.app.ports.uow import PersistenceUnitOfWork
class SqlArtifactRepository:
    def __init__(self, sessions: sessionmaker[Session], root: Path) -> None: self.sessions=sessions; self.root=root
    def save_json(self, uow: PersistenceUnitOfWork, run_id: UUID, name: str, payload: object) -> ArtifactRef:
        if Path(name).name != name: raise UnsafeArtifactPath("artifact name must be basename")
        artifact_id=uuid4(); relative=f"{run_id}/{artifact_id}-{name}"; path=resolve_artifact(self.root,relative); raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode(); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_bytes(raw); tmp.replace(path); digest=sha256(raw).hexdigest(); uow.add(RunArtifactRow(id=artifact_id,run_id=run_id,kind="json",relative_path=relative,sha256=digest,media_type="application/json",created_at=datetime.now(tz=ZoneInfo("Asia/Shanghai")))); uow.flush(); return ArtifactRef(artifact_id,run_id,name,digest,"application/json")
    def open(self, run_id: UUID, artifact_id: UUID) -> BinaryIO:
        with self.sessions() as s:
            row=s.get(RunArtifactRow,artifact_id)
            if row is None or row.run_id != run_id: raise KeyError(str(artifact_id))
            path=resolve_artifact(self.root,row.relative_path); raw=path.read_bytes()
            if sha256(raw).hexdigest()!=row.sha256: raise OSError("artifact hash mismatch")
        return path.open("rb")
