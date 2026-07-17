from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestRunSummary,
    OrderIntent,
)
from backend.app.features.backtests.ports import BacktestDecision, BacktestDecisionContext
from backend.app.ports.artifacts import ArtifactRef, ArtifactRepository
from backend.app.ports.uow import PersistenceUnitOfWork


@dataclass(frozen=True)
class FixedDecisionPort:
    intents: tuple[OrderIntent, ...]

    def decide(self, context: BacktestDecisionContext) -> BacktestDecision:
        return BacktestDecision(self.intents, context.candidate_states)


@dataclass
class MemoryBacktestRepository:
    summaries: dict[str, BacktestRunSummary] = field(default_factory=dict)
    results: dict[UUID, BacktestExperimentResult] = field(default_factory=dict)
    artifact_repositories: dict[UUID, ArtifactRepository] = field(default_factory=dict)

    def save_summary(self, summary: BacktestRunSummary) -> None:
        self.summaries[summary.run_id] = summary

    def publish_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        artifacts: ArtifactRepository,
    ) -> None:
        self.results[run_id] = result
        self.artifact_repositories[run_id] = artifacts


@dataclass
class MemoryArtifactRepository:
    refs: dict[tuple[UUID, UUID], ArtifactRef] = field(default_factory=dict)
    payloads: dict[tuple[UUID, UUID], bytes] = field(default_factory=dict)

    def save_json(
        self,
        uow: PersistenceUnitOfWork,
        run_id: UUID,
        name: str,
        payload: object,
    ) -> ArtifactRef:
        _ = uow
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        artifact_id = uuid4()
        ref = ArtifactRef(
            artifact_id=artifact_id,
            run_id=run_id,
            name=name,
            sha256=sha256(raw).hexdigest(),
            media_type="application/json",
        )
        key = (run_id, artifact_id)
        self.refs[key] = ref
        self.payloads[key] = raw
        return ref

    def open(self, run_id: UUID, artifact_id: UUID) -> BinaryIO:
        try:
            raw = self.payloads[(run_id, artifact_id)]
        except KeyError:
            raise KeyError(str(artifact_id)) from None
        return BytesIO(raw)
