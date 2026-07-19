from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import AwareDatetime

from backend.app.contracts.holdings import (
    HoldingAnalysisRequest as LegacyHoldingAnalysisRequest,
)
from backend.app.contracts.holdings import (
    HoldingAnalysisResponse as LegacyHoldingAnalysisResponse,
)
from backend.app.contracts.runs import RunKind, RunRef
from backend.app.core.clock import Clock, SystemClock
from backend.app.core.portfolio.analysis import HoldingAnalysisService as LegacyHoldingService
from backend.app.core.portfolio.models import (
    CorrectionSnapshot,
    FillSide,
    ManualFillCommand,
    PortfolioLot,
    PortfolioSnapshot,
    PositionOrigin,
)
from backend.app.ports.portfolio import PortfolioReader, PortfolioWriter

from .contracts import (
    CorrectedPositionRequest,
    HoldingAnalysisRequest,
    HoldingAnalysisResponse,
    LegacyImportProvenanceResponse,
    ManualFillRequest,
    PortfolioPositionPage,
    PositionCorrectionRequest,
)
from .repository import HoldingAnalysisNotFound, HoldingAnalysisRepository


RunSubmitter = Callable[[RunKind, dict[str, object], str | None, datetime], RunRef]


@dataclass(frozen=True)
class LegacyImportProvenance:
    batch_id: str
    manifest_sha256: str
    portfolio_id: str
    effective_at: datetime


LegacyImportProvenanceReader = Callable[[str], LegacyImportProvenance | None]


def build_router(
    service: LegacyHoldingService,
    submit: RunSubmitter | None = None,
    repository: HoldingAnalysisRepository | None = None,
    *,
    portfolio_reader: PortfolioReader | None = None,
    portfolio_writer: PortfolioWriter | None = None,
    import_provenance_reader: LegacyImportProvenanceReader | None = None,
    clock: Clock | None = None,
) -> APIRouter:
    router = APIRouter(tags=["holdings"])
    legacy = APIRouter(prefix="/holdings")
    analyses = APIRouter(prefix="/holding-analyses")
    portfolio = APIRouter(prefix="/portfolio")
    resolved_clock = clock or SystemClock()

    @legacy.post("/analysis", response_model=LegacyHoldingAnalysisResponse)
    def analyze(request: LegacyHoldingAnalysisRequest) -> LegacyHoldingAnalysisResponse:
        return service.analyze(request)

    def submit_request(
        request: HoldingAnalysisRequest,
        response: Response,
        idempotency_key: str | None,
    ) -> RunRef:
        if submit is None:
            raise RuntimeError("holding analysis submission is not configured")
        ref = submit(
            RunKind.HOLDING_ANALYSIS,
            request.model_dump(mode="json"),
            idempotency_key,
            resolved_clock.now(),
        )
        response.headers["Location"] = ref.links.self
        return ref

    @legacy.post("/analysis/submit", response_model=RunRef, status_code=202)
    def submit_legacy_analysis(
        request: HoldingAnalysisRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        return submit_request(request, response, idempotency_key)

    @analyses.post("", response_model=RunRef, status_code=202)
    def submit_analysis(
        request: HoldingAnalysisRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RunRef:
        return submit_request(request, response, idempotency_key)

    def load_result(run_id: str) -> HoldingAnalysisResponse:
        if repository is None:
            raise HoldingAnalysisNotFound(run_id)
        value = repository.get(run_id)
        if value is None:
            raise HoldingAnalysisNotFound(run_id)
        return HoldingAnalysisResponse.from_domain(value)

    def load_latest(portfolio_id: str) -> HoldingAnalysisResponse:
        if repository is None:
            raise HoldingAnalysisNotFound(portfolio_id)
        value = repository.latest(portfolio_id)
        if value is None:
            raise HoldingAnalysisNotFound(portfolio_id)
        return HoldingAnalysisResponse.from_domain(value)

    @legacy.get("/analysis/latest", response_model=HoldingAnalysisResponse)
    def latest_legacy_result(portfolio_id: str = "default") -> HoldingAnalysisResponse:
        return load_latest(portfolio_id)

    @legacy.get("/analysis/{run_id}", response_model=HoldingAnalysisResponse)
    def legacy_result(run_id: str) -> HoldingAnalysisResponse:
        return load_result(run_id)

    @analyses.get("/latest", response_model=HoldingAnalysisResponse)
    def latest_result(portfolio_id: str = "default") -> HoldingAnalysisResponse:
        return load_latest(portfolio_id)

    @analyses.get("/{run_id}", response_model=HoldingAnalysisResponse)
    def result(run_id: str) -> HoldingAnalysisResponse:
        return load_result(run_id)

    def require_portfolio_reader() -> PortfolioReader:
        if portfolio_reader is None:
            raise RuntimeError("portfolio reader is not configured")
        return portfolio_reader

    def require_portfolio_writer() -> PortfolioWriter:
        if portfolio_writer is None:
            raise RuntimeError("portfolio writer is not configured")
        return portfolio_writer

    @portfolio.get("/positions", response_model=PortfolioPositionPage)
    def positions(
        portfolio_id: str = "default",
        as_of_time: AwareDatetime | None = None,
        import_batch_id: str | None = None,
        import_manifest_sha256: str | None = None,
    ) -> PortfolioPositionPage:
        decision_time = as_of_time or resolved_clock.now()
        snapshot = require_portfolio_reader().snapshot(
            portfolio_id=portfolio_id,
            as_of_time=decision_time,
        )
        return PortfolioPositionPage.from_domain(
            snapshot,
            _verified_import_provenance(
                snapshot,
                import_batch_id,
                import_manifest_sha256,
                import_provenance_reader,
            ),
        )

    @portfolio.put("/positions", response_model=PortfolioPositionPage)
    def correct_positions(request: PositionCorrectionRequest) -> PortfolioPositionPage:
        correction_time = max(position.effective_at for position in request.positions)
        reader = require_portfolio_reader()
        current = reader.snapshot(
            portfolio_id=request.portfolio_id,
            as_of_time=correction_time,
        )
        current_lots = {lot.security_id: lot for lot in current.lots}
        corrected_security_ids = {str(position.security_id) for position in request.positions}
        unchanged_lots = tuple(
            lot for lot in current.lots if lot.security_id not in corrected_security_ids
        )
        corrected_lots = tuple(
            _corrected_lot(position, current_lots.get(str(position.security_id)))
            for position in request.positions
            if position.quantity > 0
        )
        lots = tuple(sorted((*unchanged_lots, *corrected_lots), key=lambda lot: lot.lot_id))
        corrected = require_portfolio_writer().replace_positions_for_correction(
            CorrectionSnapshot(
                portfolio_id=request.portfolio_id,
                as_of_time=correction_time,
                cash=current.cash,
                equity=current.equity,
                lots=lots,
            ),
            request.expected_version,
            request.reason,
        )
        return PortfolioPositionPage.from_domain(corrected)

    @portfolio.post("/fills", response_model=PortfolioPositionPage)
    def record_manual_fill(request: ManualFillRequest) -> PortfolioPositionPage:
        reader = require_portfolio_reader()
        current = reader.snapshot(
            portfolio_id=request.portfolio_id,
            as_of_time=request.executed_at,
        )
        strategy_book = next(
            (
                position.strategy_book
                for position in current.positions
                if position.security_id == request.security_id
            ),
            None,
        )
        updated = require_portfolio_writer().record_manual_fill(
            ManualFillCommand(
                portfolio_id=request.portfolio_id,
                security_id=request.security_id,
                side=FillSide(request.side),
                quantity=request.quantity,
                price=request.price,
                fee=request.fee,
                filled_at=request.executed_at,
                strategy_book=strategy_book,
            ),
            request.expected_version,
        )
        return PortfolioPositionPage.from_domain(updated)

    router.include_router(legacy)
    router.include_router(analyses)
    router.include_router(portfolio)
    return router


def _verified_import_provenance(
    snapshot: PortfolioSnapshot,
    batch_id: str | None,
    manifest_sha256: str | None,
    reader: LegacyImportProvenanceReader | None,
) -> LegacyImportProvenanceResponse | None:
    if batch_id is None and manifest_sha256 is None:
        return None
    if batch_id is None or manifest_sha256 is None or reader is None:
        raise HTTPException(status_code=409, detail="legacy import provenance is invalid")
    lots = getattr(snapshot, "lots", ())
    actual_batch_ids = {
        lot.batch_id
        for lot in lots
        if lot.origin is PositionOrigin.LEGACY_OPENING_BALANCE and lot.quantity > 0
    }
    provenance = reader(batch_id)
    if (
        batch_id not in actual_batch_ids
        or provenance is None
        or provenance.batch_id != batch_id
        or provenance.portfolio_id != snapshot.portfolio_id
        or provenance.effective_at > snapshot.as_of_time
        or provenance.manifest_sha256 != manifest_sha256
    ):
        raise HTTPException(status_code=409, detail="legacy import provenance is invalid")
    return LegacyImportProvenanceResponse(
        batch_id=provenance.batch_id,
        manifest_sha256=provenance.manifest_sha256,
    )


def _corrected_lot(
    position: CorrectedPositionRequest,
    current: PortfolioLot | None,
) -> PortfolioLot:
    security_id = str(position.security_id)
    quantity = int(position.quantity)
    effective_at = position.effective_at
    if current is None:
        return PortfolioLot(
            lot_id=f"correction:{security_id}",
            security_id=security_id,
            quantity=quantity,
            available_to_sell=quantity,
            average_cost=position.average_cost,
            effective_at=effective_at,
            origin=PositionOrigin.RECORDED_TRADE,
            strategy_book=None,
            entry_score=None,
            initial_risk_per_share=None,
            effective_stop=None,
            highest_close=None,
            add_count=0,
        )
    return PortfolioLot(
        lot_id=current.lot_id,
        security_id=security_id,
        quantity=quantity,
        available_to_sell=min(quantity, current.available_to_sell),
        average_cost=position.average_cost,
        effective_at=effective_at,
        origin=current.origin,
        strategy_book=current.strategy_book,
        entry_score=current.entry_score,
        initial_risk_per_share=current.initial_risk_per_share,
        effective_stop=current.effective_stop,
        highest_close=current.highest_close,
        add_count=current.add_count,
        batch_id=current.batch_id,
        buy_date=current.buy_date,
    )
