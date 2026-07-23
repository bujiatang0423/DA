from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from backend.app.core.market.pit_models import PointInTimeSnapshot, SnapshotScope
from backend.app.core.market.strategy_inputs import StrategyInputBuilder, StrategyInputError
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.core.strategy.types import StrategyEvaluation, StrategyEvaluationRequest
from backend.app.ports.point_in_time import PointInTimeWarehouse
from backend.app.ports.portfolio import PortfolioReader
from backend.app.ports.strategy import StrategyDecisionPort

from .models import HoldingAnalysisResult, HoldingImportProvenance, HoldingRiskSummary
from .quality import holding_evidence, llm_grade_from_snapshot
from .repository import HoldingAnalysisRepository
from .strategy_projection import project_position


class HoldingAnalysisInvariantError(RuntimeError):
    code = "HOLDING_ANALYSIS_INVARIANT_VIOLATION"


class HoldingMarketDataMissing(RuntimeError):
    code = "HOLDING_MARKET_DATA_MISSING"


class FinancialEvidenceRefresher(Protocol):
    """Ensures official financial evidence is current for a holding scope."""

    def refresh(self, *, security_ids: tuple[str, ...], as_of_time: datetime) -> object: ...


@dataclass(frozen=True, slots=True)
class HoldingAnalysisCommand:
    run_id: str
    portfolio_id: str
    as_of_time: datetime
    strategy_version: Literal["v2.12"] = "v2.12"
    import_batch_id: str | None = None
    import_manifest_sha256: str | None = None


class HoldingAnalysisService:
    def __init__(
        self,
        warehouse: PointInTimeWarehouse,
        portfolios: PortfolioReader,
        builder: StrategyInputBuilder,
        strategy: StrategyDecisionPort,
        repository: HoldingAnalysisRepository,
        financial_evidence_refresher: FinancialEvidenceRefresher | None = None,
    ) -> None:
        self._warehouse = warehouse
        self._portfolios = portfolios
        self._builder = builder
        self._strategy = strategy
        self._repository = repository
        self._financial_evidence_refresher = financial_evidence_refresher

    def run(self, command: HoldingAnalysisCommand) -> HoldingAnalysisResult:
        if command.as_of_time.tzinfo is None or command.as_of_time.utcoffset() is None:
            raise HoldingAnalysisInvariantError("holding as_of_time must be timezone-aware")

        portfolio = self._portfolios.snapshot(
            portfolio_id=command.portfolio_id,
            as_of_time=command.as_of_time,
        )
        security_ids = tuple(sorted({position.security_id for position in portfolio.positions}))
        initial_security_ids = security_ids
        effective_command = command
        if self._financial_evidence_refresher is not None:
            refresh_result = self._financial_evidence_refresher.refresh(
                security_ids=security_ids,
                as_of_time=command.as_of_time,
            )
            available_at = getattr(refresh_result, "available_at", None)
            if isinstance(available_at, datetime) and available_at > command.as_of_time:
                effective_command = replace(command, as_of_time=available_at)
                portfolio = self._portfolios.snapshot(
                    portfolio_id=command.portfolio_id,
                    as_of_time=available_at,
                )
                security_ids = tuple(
                    sorted({position.security_id for position in portfolio.positions})
                )
                added_security_ids = tuple(
                    security_id
                    for security_id in security_ids
                    if security_id not in initial_security_ids
                )
                if added_security_ids:
                    self._financial_evidence_refresher.refresh(
                        security_ids=added_security_ids,
                        as_of_time=effective_command.as_of_time,
                    )
        snapshot = self._warehouse.snapshot(
            as_of_time=effective_command.as_of_time,
            scope=SnapshotScope.holding_analysis(security_ids),
        )
        self._validate_inputs(effective_command, portfolio, snapshot)
        self._validate_import_provenance(effective_command, portfolio)
        if snapshot.quality.has_errors:
            raise HoldingMarketDataMissing(self._missing_data_detail(snapshot))

        try:
            prepared = self._builder.build(
                snapshot=snapshot,
                portfolio=portfolio,
                strategy_version=effective_command.strategy_version,
            )
        except StrategyInputError as exc:
            raise HoldingMarketDataMissing(
                f"{HoldingMarketDataMissing.code}: strategy inputs unavailable"
            ) from exc
        evaluation = self._strategy.evaluate(prepared)
        self._validate_evaluation(effective_command, snapshot, prepared, evaluation)

        evaluations_by_security = {item.security_id: item for item in evaluation.securities}
        missing = tuple(sid for sid in security_ids if sid not in evaluations_by_security)
        if missing:
            raise HoldingMarketDataMissing(
                f"{HoldingMarketDataMissing.code}: missing evaluations for {','.join(missing)}"
            )
        invalid_close_ids = tuple(
            security_id for security_id, item in evaluations_by_security.items() if item.close <= 0
        )
        if invalid_close_ids:
            raise HoldingMarketDataMissing(
                f"{HoldingMarketDataMissing.code}: invalid close for {','.join(invalid_close_ids)}"
            )
        items = tuple(
            project_position(
                position,
                evaluations_by_security[position.security_id],
                evidence_refs=evidence.refs,
                evidence_available=evidence.is_available,
            )
            for position in portfolio.positions
            for evidence in (holding_evidence(snapshot, position.security_id),)
        )
        portfolio_view = evaluation.portfolio_summary
        result = HoldingAnalysisResult(
            run_id=effective_command.run_id,
            portfolio_id=effective_command.portfolio_id,
            as_of_time=effective_command.as_of_time,
            strategy_version=effective_command.strategy_version,
            manifest_hash=snapshot.manifest_hash,
            data_grade=snapshot.data_grade,
            llm_grade=llm_grade_from_snapshot(snapshot),
            summary=HoldingRiskSummary(
                equity=portfolio.equity,
                cash=portfolio.cash,
                gross_exposure_pct=Decimal(str(portfolio_view.gross_exposure_pct)),
                portfolio_risk_pct=Decimal(str(portfolio_view.portfolio_risk_pct)),
                market_state=portfolio_view.market_state.value,
            ),
            items=items,
            portfolio_imports=tuple(
                HoldingImportProvenance(batch_id, manifest_sha256)
                for batch_id, manifest_sha256 in sorted(
                    {
                        (lot.batch_id, lot.import_manifest_sha256)
                        for lot in portfolio.lots
                        if lot.origin.value == "legacy_opening_balance"
                        and lot.import_manifest_sha256 is not None
                    }
                )
            ),
        )
        self._repository.save(result)
        return result

    @staticmethod
    def _validate_inputs(
        command: HoldingAnalysisCommand,
        portfolio: PortfolioSnapshot,
        snapshot: PointInTimeSnapshot,
    ) -> None:
        if portfolio.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("portfolio decision time mismatch")
        if snapshot.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("point-in-time snapshot mismatch")

    @staticmethod
    def _validate_evaluation(
        command: HoldingAnalysisCommand,
        snapshot: PointInTimeSnapshot,
        prepared: StrategyEvaluationRequest,
        evaluation: StrategyEvaluation,
    ) -> None:
        prepared_as_of = getattr(getattr(prepared, "as_of", None), "as_of_time", None)
        prepared_strategy = getattr(getattr(prepared, "strategy", None), "version", None)
        prepared_manifest = getattr(prepared, "manifest_hash", None)
        if prepared_as_of != command.as_of_time or evaluation.as_of_time != command.as_of_time:
            raise HoldingAnalysisInvariantError("strategy decision time mismatch")
        if prepared_strategy != command.strategy_version:
            raise HoldingAnalysisInvariantError("prepared strategy version mismatch")
        if evaluation.strategy_version != command.strategy_version:
            raise HoldingAnalysisInvariantError("evaluation strategy version mismatch")
        if prepared_manifest != snapshot.manifest_hash:
            raise HoldingAnalysisInvariantError("prepared manifest mismatch")
        if evaluation.manifest_hash != snapshot.manifest_hash:
            raise HoldingAnalysisInvariantError("evaluation manifest mismatch")

    @staticmethod
    def _validate_import_provenance(
        command: HoldingAnalysisCommand,
        portfolio: PortfolioSnapshot,
    ) -> None:
        if (command.import_batch_id is None) != (command.import_manifest_sha256 is None):
            raise HoldingAnalysisInvariantError(
                "import batch and manifest must be supplied together"
            )
        if command.import_batch_id is None or command.import_manifest_sha256 is None:
            return
        matching_lots = tuple(
            lot
            for lot in portfolio.lots
            if lot.batch_id == command.import_batch_id
            and lot.origin.value == "legacy_opening_balance"
        )
        if not matching_lots:
            raise HoldingAnalysisInvariantError(
                "requested import batch is not in the portfolio snapshot"
            )
        if any(
            lot.import_manifest_sha256 != command.import_manifest_sha256
            for lot in matching_lots
        ):
            raise HoldingAnalysisInvariantError(
                "requested import manifest does not match the portfolio snapshot"
            )

    @staticmethod
    def _missing_data_detail(snapshot: PointInTimeSnapshot) -> str:
        codes = ",".join(sorted({issue.code for issue in snapshot.quality.issues}))
        return f"{HoldingMarketDataMissing.code}: {codes or 'snapshot quality error'}"


V212HoldingAnalysisService = HoldingAnalysisService
