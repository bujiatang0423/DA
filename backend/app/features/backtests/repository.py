from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.contracts.runs import Page
from backend.app.features.backtests.db_models import (
    BacktestCurvePointRow,
    BacktestGroupResultRow,
    BacktestRejectedAttemptRow,
    BacktestResultRow,
    BacktestTradeRow,
)
from backend.app.features.backtests.models import (
    BacktestExperimentResult,
    BacktestGroupResult,
    BacktestGroupSummary,
    BacktestRunSummary,
    StrategyGroup,
)
from backend.app.ports.artifacts import ArtifactRepository


class BacktestResultConflict(RuntimeError):
    """A completed run cannot be overwritten with different research evidence."""


class BacktestResultRepository(Protocol):
    def save_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        *,
        created_at: datetime | None = None,
    ) -> None: ...

    def fetch_result(self, run_id: UUID) -> BacktestExperimentResult | None: ...

    def fetch_summary(self, run_id: UUID) -> BacktestRunSummary: ...

    def page_curve(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]: ...

    def page_trades(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]: ...

    def page_rejected_attempts(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]: ...


class SqlBacktestRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        *,
        created_at: datetime | None = None,
    ) -> None:
        try:
            with self._session_factory.begin() as session:
                self._save_result(session, run_id, result, created_at)
        except IntegrityError as exc:
            self._resolve_duplicate(run_id, result, exc)

    def publish_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        artifacts: ArtifactRepository,
    ) -> None:
        try:
            with self._session_factory.begin() as session:
                if not self._save_result(session, run_id, result, None):
                    return
                artifacts.save_json(
                    session, run_id, "backtest-result.json", result.model_dump(mode="json")
                )
        except IntegrityError as exc:
            self._resolve_duplicate(run_id, result, exc)

    def fetch_result(self, run_id: UUID) -> BacktestExperimentResult | None:
        with self._session_factory() as session:
            row = session.get(BacktestResultRow, run_id)
            if row is None:
                return None
            groups = tuple(
                _decode_group(group, self._group_payloads(session, run_id, group.group))
                for group in session.scalars(
                    select(BacktestGroupResultRow)
                    .where(BacktestGroupResultRow.run_id == run_id)
                    .order_by(BacktestGroupResultRow.group)
                )
            )
            return BacktestExperimentResult.model_validate(
                {
                    "request": row.request_payload,
                    "input_manifest_hash": row.input_manifest_hash,
                    "groups": groups,
                    "warnings": row.warnings,
                }
            )

    def fetch_summary(self, run_id: UUID) -> BacktestRunSummary:
        with self._session_factory() as session:
            row = session.get(BacktestResultRow, run_id)
            if row is None:
                raise KeyError(str(run_id))
            groups = tuple(
                BacktestGroupSummary(
                    group=StrategyGroup(group.group),
                    data_grade=DataGrade(group.data_grade),
                    llm_grade=LlmGrade(group.llm_grade),
                    input_manifest_hash=group.input_manifest_hash,
                    metrics=group.metrics,
                )
                for group in session.scalars(
                    select(BacktestGroupResultRow)
                    .where(BacktestGroupResultRow.run_id == run_id)
                    .order_by(BacktestGroupResultRow.group)
                )
            )
            return BacktestRunSummary(
                run_id=str(run_id),
                status="succeeded",
                strategy_version=row.strategy_version,
                input_manifest_hash=row.input_manifest_hash,
                groups=groups,
                created_at=row.created_at,
            )

    def page_curve(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return self._page(BacktestCurvePointRow, run_id, group, limit, cursor)

    def page_trades(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return self._page(BacktestTradeRow, run_id, group, limit, cursor)

    def page_rejected_attempts(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return self._page(BacktestRejectedAttemptRow, run_id, group, limit, cursor)

    def _save_group(self, session: Session, run_id: UUID, result: BacktestGroupResult) -> None:
        group = result.group.value
        session.add(
            BacktestGroupResultRow(
                run_id=run_id,
                group=group,
                data_grade=result.data_grade.value,
                llm_grade=result.llm_grade.value,
                input_manifest_hash=result.input_manifest_hash,
                metrics=result.metrics,
                metric_details=result.metric_details,
                comparison_inputs=result.comparison_inputs,
                out_of_sample_start=result.out_of_sample_start.isoformat()
                if result.out_of_sample_start
                else None,
                warnings=list(result.warnings),
            )
        )
        session.add_all(
            BacktestCurvePointRow(
                run_id=run_id,
                group=group,
                ordinal=index,
                cursor=_cursor(point, index),
                payload=point,
            )
            for index, point in enumerate(result.equity_curve)
        )
        session.add_all(
            BacktestTradeRow(
                run_id=run_id,
                group=group,
                ordinal=index,
                cursor=_cursor(item, index),
                payload=item,
            )
            for index, item in enumerate(result.trades)
        )
        session.add_all(
            BacktestRejectedAttemptRow(
                run_id=run_id,
                group=group,
                ordinal=index,
                cursor=_cursor(item, index),
                payload=item,
            )
            for index, item in enumerate(result.rejected_attempts)
        )

    def _save_result(
        self,
        session: Session,
        run_id: UUID,
        result: BacktestExperimentResult,
        created_at: datetime | None,
    ) -> bool:
        content_hash = _content_hash(result)
        existing = session.get(BacktestResultRow, run_id)
        if existing is not None:
            if existing.content_hash != content_hash:
                raise BacktestResultConflict(str(run_id))
            return False
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        session.add(
            BacktestResultRow(
                run_id=run_id,
                created_at=timestamp,
                strategy_version=result.request.strategy_version,
                input_manifest_hash=result.input_manifest_hash,
                request_payload=result.request.model_dump(mode="json"),
                warnings=list(result.warnings),
                content_hash=content_hash,
            )
        )
        session.flush()
        for group_result in result.groups:
            self._save_group(session, run_id, group_result)
        return True

    def _resolve_duplicate(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        original_error: IntegrityError,
    ) -> None:
        with self._session_factory() as session:
            existing = session.get(BacktestResultRow, run_id)
            if existing is None:
                raise original_error
            if existing.content_hash != _content_hash(result):
                raise BacktestResultConflict(str(run_id)) from original_error

    def _group_payloads(
        self, session: Session, run_id: UUID, group: str
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        return (
            list(
                session.scalars(
                    select(BacktestCurvePointRow.payload)
                    .where(
                        BacktestCurvePointRow.run_id == run_id, BacktestCurvePointRow.group == group
                    )
                    .order_by(BacktestCurvePointRow.ordinal)
                )
            ),
            list(
                session.scalars(
                    select(BacktestTradeRow.payload)
                    .where(BacktestTradeRow.run_id == run_id, BacktestTradeRow.group == group)
                    .order_by(BacktestTradeRow.ordinal)
                )
            ),
            list(
                session.scalars(
                    select(BacktestRejectedAttemptRow.payload)
                    .where(
                        BacktestRejectedAttemptRow.run_id == run_id,
                        BacktestRejectedAttemptRow.group == group,
                    )
                    .order_by(BacktestRejectedAttemptRow.ordinal)
                )
            ),
        )

    def _page(
        self,
        model: type[BacktestCurvePointRow]
        | type[BacktestTradeRow]
        | type[BacktestRejectedAttemptRow],
        run_id: UUID,
        group: StrategyGroup,
        limit: int,
        cursor: str | None,
    ) -> Page[dict[str, str]]:
        with self._session_factory() as session:
            start = 0
            if cursor is not None:
                ordinal = session.scalar(
                    select(model.ordinal).where(
                        model.run_id == run_id,
                        model.group == group.value,
                        model.cursor == cursor,
                    )
                )
                if ordinal is None:
                    raise KeyError(cursor)
                start = ordinal
            rows = list(
                session.scalars(
                    select(model)
                    .where(
                        model.run_id == run_id, model.group == group.value, model.ordinal >= start
                    )
                    .order_by(model.ordinal)
                    .limit(limit + 1)
                )
            )
            next_cursor = rows[limit].cursor if len(rows) > limit else None
            return Page(items=[row.payload for row in rows[:limit]], next_cursor=next_cursor)


class MemoryBacktestResultRepository:
    def __init__(self) -> None:
        self._results: dict[UUID, tuple[BacktestExperimentResult, datetime]] = {}

    def save_result(
        self,
        run_id: UUID,
        result: BacktestExperimentResult,
        *,
        created_at: datetime | None = None,
    ) -> None:
        existing = self._results.get(run_id)
        if existing is not None and _content_hash(existing[0]) != _content_hash(result):
            raise BacktestResultConflict(str(run_id))
        self._results.setdefault(run_id, (result, created_at or datetime.now(UTC)))

    def fetch_result(self, run_id: UUID) -> BacktestExperimentResult | None:
        item = self._results.get(run_id)
        return item[0] if item else None

    def fetch_summary(self, run_id: UUID) -> BacktestRunSummary:
        result, created_at = self._results[run_id]
        return BacktestRunSummary(
            run_id=str(run_id),
            status="succeeded",
            strategy_version=result.request.strategy_version,
            input_manifest_hash=result.input_manifest_hash,
            groups=tuple(
                BacktestGroupSummary(
                    group=item.group,
                    data_grade=item.data_grade,
                    llm_grade=item.llm_grade,
                    input_manifest_hash=item.input_manifest_hash,
                    metrics=item.metrics,
                )
                for item in result.groups
            ),
            created_at=created_at,
        )

    def page_curve(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return _memory_page(self._group(run_id, group).equity_curve, limit, cursor)

    def page_trades(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return _memory_page(self._group(run_id, group).trades, limit, cursor)

    def page_rejected_attempts(
        self, run_id: UUID, group: StrategyGroup, *, limit: int, cursor: str | None = None
    ) -> Page[dict[str, str]]:
        return _memory_page(self._group(run_id, group).rejected_attempts, limit, cursor)

    def _group(self, run_id: UUID, group: StrategyGroup) -> BacktestGroupResult:
        result = self.fetch_result(run_id)
        if result is None:
            raise KeyError(str(run_id))
        return next(item for item in result.groups if item.group is group)


def _decode_group(
    row: BacktestGroupResultRow,
    payloads: tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]],
) -> BacktestGroupResult:
    curve, trades, rejected_attempts = payloads
    return BacktestGroupResult(
        group=StrategyGroup(row.group),
        data_grade=DataGrade(row.data_grade),
        llm_grade=LlmGrade(row.llm_grade),
        input_manifest_hash=row.input_manifest_hash,
        equity_curve=curve,
        trades=trades,
        rejected_attempts=rejected_attempts,
        metrics=row.metrics,
        comparison_inputs=row.comparison_inputs,
        out_of_sample_start=date.fromisoformat(row.out_of_sample_start)
        if row.out_of_sample_start
        else None,
        metric_details=row.metric_details,
        warnings=row.warnings,
    )


def _content_hash(result: BacktestExperimentResult) -> str:
    payload = result.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def _cursor(item: dict[str, str], index: int) -> str:
    return item.get("order_id", f"item-{index + 1}")


def _memory_page(
    items: list[dict[str, str]], limit: int, cursor: str | None
) -> Page[dict[str, str]]:
    start = 0
    if cursor is not None:
        cursors = [_cursor(item, index) for index, item in enumerate(items)]
        start = cursors.index(cursor)
    page = items[start : start + limit]
    next_index = start + limit
    next_cursor = _cursor(items[next_index], next_index) if next_index < len(items) else None
    return Page(items=page, next_cursor=next_cursor)
