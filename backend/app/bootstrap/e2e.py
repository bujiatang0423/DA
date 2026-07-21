"""Explicit guard for the local browser-test composition.

This module intentionally has no production import path.  The E2E entrypoint
must opt in before it can use frozen test data or reset its local database.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.contracts.grades import DataGrade
from backend.app.core.market.pit_models import (
    DataKind,
    LineageRef,
    PointInTimeSnapshot,
    SecurityObservation,
    SnapshotQuality,
    SnapshotScope,
    TemporalRecord,
)
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text

from backend.app.bootstrap.application import create_app
from backend.app.bootstrap.composition import build_components
from backend.app.bootstrap.settings import Settings
from backend.app.features.backtests.module import build_backtests_feature
from backend.app.features.backtests.repository import SqlBacktestRepository
from backend.app.features.candidates.module import build_candidate_feature
from backend.app.features.holdings.module import build_holdings_feature
from backend.app.features.runs.module import build_runs_feature
from backend.app.features.runs.service import RunsService
from backend.app.infrastructure.persistence.portfolio_maintenance import (
    SqlPortfolioMaintenanceService,
)
from backend.app.infrastructure.persistence.portfolio_reader import SqlPortfolioReader
from backend.app.infrastructure.tasks.handlers import HandlerRegistry
from backend.app.infrastructure.tasks.health import WorkerLeaseStore
from backend.app.infrastructure.tasks.worker import Worker, build_worker
from backend.app.worker_main import register_worker_handlers
from backend.app.infrastructure.market.strict_bundle import PitBundleManifest
from backend.app.infrastructure.market.strict_certificates import (
    SqlPitCertificateAuthority,
    bundle_set_hash_for,
)
from backend.app.infrastructure.market.strict_ingest import StrictPitIngestor
from backend.app.infrastructure.persistence.strict_pit_rows import PitAuditReportRow
from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioSnapshotProjectionRow,
    PortfolioVersionRow,
)


class E2EConfigurationError(ValueError):
    """Raised when the local browser-test process is not explicitly isolated."""


E2E_BACKTEST_START = datetime(2020, 6, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
E2E_BACKTEST_END = datetime(2020, 7, 2, tzinfo=ZoneInfo("Asia/Shanghai"))
_STRICT_E2E_TABLES = (
    "pit_certificates, pit_audit_reports, pit_bundles, security_master_history, "
    "security_status_daily, trading_calendar, daily_bars_raw, index_daily_bars, "
    "market_breadth, corporate_actions, adjustment_factors, industry_membership_history, "
    "theme_membership_history, financial_disclosures, financial_facts, policy_documents, "
    "fee_schedules"
)
_E2E_RUN_TABLES = "runs, worker_leases"
_E2E_PORTFOLIO_TABLES = (
    "portfolio_audit_events, portfolio_lot_projections, portfolio_snapshot_projections, "
    "portfolio_versions"
)


def require_local_e2e_mode(environment: Mapping[str, str]) -> None:
    """Reject accidental use of the E2E process outside an explicit test mode."""
    if environment.get("DA_E2E_LOCAL") != "1":
        raise E2EConfigurationError("DA_E2E_LOCAL=1 is required for the local E2E harness")
    if environment.get("DA_ENVIRONMENT") != "test":
        raise E2EConfigurationError("the local E2E harness requires a test environment")


class FrozenE2EWarehouse:
    """A local-only PIT source for candidate and holding browser workflows."""

    def snapshot(
        self,
        *,
        as_of_time: datetime,
        scope: SnapshotScope,
    ) -> PointInTimeSnapshot:
        source_hash = "e" * 64
        breadth = TemporalRecord(
            record_id="local-e2e-market-breadth",
            kind=DataKind.MARKET_BREADTH,
            entity_id="MARKET:local-e2e",
            event_time=as_of_time,
            observed_at=as_of_time,
            available_at=as_of_time,
            source_artifact_hash=source_hash,
            payload={"breadth": 0.6, "security_count": 1},
        )
        index_bars = tuple(
            {
                "trade_date": (as_of_time.date() - timedelta(days=60 - i)).isoformat(),
                "open": 100 + i,
                "high": 101 + i,
                "low": 99 + i,
                "close": 100 + i,
                "volume": 1_000_000,
                "amount": 100_000_000,
            }
            for i in range(60)
        )
        index = TemporalRecord(
            "local-e2e-index",
            DataKind.INDEX_DAILY_BAR,
            "MARKET:local-e2e",
            as_of_time,
            as_of_time,
            as_of_time,
            source_hash,
            {"close": 159, "bars": index_bars},
        )
        market_records: list[TemporalRecord] = [breadth, index]
        observations: list[SecurityObservation] = []
        for offset, security_id in enumerate(("000001.SZ", "000002.SZ", "000003.SZ")):
            artifact_hash = sha256(f"local-e2e:{security_id}".encode()).hexdigest()
            master = TemporalRecord(
                f"security-master:{security_id}",
                DataKind.SECURITY_MASTER,
                security_id,
                as_of_time,
                as_of_time,
                as_of_time,
                artifact_hash,
                {
                    "name": f"Fixture {security_id}",
                    "listing_days": 1000,
                    "status": "SUSPENDED" if offset == 2 else "ACTIVE",
                    "industry_id": "fixture",
                },
            )
            bars = tuple(
                TemporalRecord(
                    f"daily-bar:{security_id}:{i}",
                    DataKind.DAILY_BAR_RAW,
                    security_id,
                    as_of_time,
                    as_of_time,
                    as_of_time,
                    artifact_hash,
                    {
                        "trade_date": (as_of_time.date() - timedelta(days=20 - i)).isoformat(),
                        "open": 100 + i * (0.001 if offset == 0 else 1) + offset,
                        "high": 100 + i * (0.001 if offset == 0 else 1) + offset + 0.01,
                        "low": 100 + i * (0.001 if offset == 0 else 1) + offset - 0.01,
                        "close": 100 + i * (0.001 if offset == 0 else 1) + offset,
                        "volume": 1_000_000,
                        "amount": 100_000_000,
                    },
                )
                for i in range(20)
            )
            facts = tuple(
                TemporalRecord(
                    f"financial-fact:{security_id}:{metric}",
                    DataKind.FINANCIAL_FACT,
                    security_id,
                    as_of_time,
                    as_of_time,
                    as_of_time,
                    artifact_hash,
                    {"metric": metric, "value": 60},
                )
                for metric in ("roe", "revenue_growth")
            )
            policy_hash = sha256(f"policy:{security_id}".encode()).hexdigest()
            llm_hash = sha256(f"llm:{security_id}".encode()).hexdigest()
            market_records.extend(
                (
                    TemporalRecord(
                        f"policy:{security_id}",
                        DataKind.POLICY_DOCUMENT,
                        f"MARKET:POLICY:{security_id}",
                        as_of_time,
                        as_of_time,
                        as_of_time,
                        policy_hash,
                        {"security_ids": security_id, "strength": 80, "relevance": 80},
                    ),
                    TemporalRecord(
                        f"llm:{security_id}",
                        DataKind.LLM_FACTOR,
                        f"MARKET:LLM:{security_id}",
                        as_of_time,
                        as_of_time,
                        as_of_time,
                        llm_hash,
                        {
                            "security_ids": security_id,
                            "first_observed_at": as_of_time.isoformat(),
                            "grade": "forward_observed",
                            "valid": True,
                            "policy_direction": "supportive",
                        },
                    ),
                )
            )
            observations.append(SecurityObservation(security_id, (master, *bars, *facts)))
        return PointInTimeSnapshot(
            as_of_time=as_of_time,
            scope=scope,
            data_grade=DataGrade.RESEARCH,
            market_inputs=tuple(market_records),
            security_observations=tuple(observations),
            quality=SnapshotQuality(()),
            lineage=tuple(
                LineageRef(f"local-e2e-{record.source_artifact_hash[:12]}", "test_only", record.source_artifact_hash)
                for record in (*market_records, *(r for o in observations for r in o.records))
            ),
            manifest_hash="f" * 64,
        )


def build_local_e2e_application(
    settings: Settings,
    sessions: sessionmaker[Session],
) -> FastAPI:
    """Compose actual API routes over local SQL state and frozen test inputs."""
    if settings.environment != "test" or settings.provider_mode != "fake":
        raise E2EConfigurationError("the local E2E application requires test fake-provider mode")
    components = build_components(settings, sessions, fake_warehouse=FrozenE2EWarehouse())
    runs = RunsService(sessions)
    return create_app(
        (
            build_runs_feature(runs),
            build_candidate_feature(
                runs.submit,
                repository=components.candidate_service.repository,
                service=components.candidate_service,
            ),
            build_holdings_feature(
                SqlPortfolioReader(sessions),
                SqlPortfolioMaintenanceService(sessions),
                runs.submit,
                components.holding_repository,
                components.holding_service,
                components.portfolio_writer,
            ),
            build_backtests_feature(runs.submit, SqlBacktestRepository(sessions)),
        ),
    )


def build_local_e2e_worker(
    settings: Settings,
    sessions: sessionmaker[Session],
) -> Worker:
    """Build the same SQL-backed worker lifecycle used by the local browser API."""
    if settings.environment != "test" or settings.provider_mode != "fake":
        raise E2EConfigurationError("the local E2E worker requires test fake-provider mode")
    components = build_components(settings, sessions, fake_warehouse=FrozenE2EWarehouse())
    handlers = HandlerRegistry()
    register_worker_handlers(settings, sessions, components, handlers)
    return build_worker(
        RunsService(sessions),
        handlers,
        lambda: datetime.now(UTC),
        WorkerLeaseStore(sessions),
        "local-e2e-worker",
        stale_after_seconds=settings.worker_stale_after_seconds,
        heartbeat_interval_seconds=0.1,
    )


def bootstrap_local_e2e_strict_pit(
    settings: Settings,
    sessions: sessionmaker[Session],
) -> None:
    """Load and certify the frozen two-session bundle used only by browser tests."""
    if settings.environment != "test" or settings.provider_mode != "fake":
        raise E2EConfigurationError("the local E2E PIT bootstrap requires test fake-provider mode")
    if settings.pit_approval_secret is None or len(settings.pit_approval_secret) < 32:
        raise E2EConfigurationError("the local E2E PIT bootstrap requires an approval secret")

    bundle = PitBundleManifest.load(_fixture_root())
    certified_as_of = datetime.combine(E2E_BACKTEST_START.date(), time(15, 30), E2E_BACKTEST_START.tzinfo)
    certificate_scopes = (
        (
            "local-e2e-pit-decision",
            SnapshotScope.backtest((), E2E_BACKTEST_START),
        ),
        (
            "local-e2e-pit-execution",
            SnapshotScope(
                ("000001.SZ",),
                (
                    DataKind.DAILY_BAR_RAW,
                    DataKind.SECURITY_STATUS,
                    DataKind.FEE_SCHEDULE,
                ),
            ),
        ),
    )
    with sessions() as session:
        session.execute(text(f"TRUNCATE TABLE {_E2E_RUN_TABLES} CASCADE"))
        session.execute(text(f"TRUNCATE TABLE {_E2E_PORTFOLIO_TABLES} CASCADE"))
        session.execute(text(f"TRUNCATE TABLE {_STRICT_E2E_TABLES} CASCADE"))
        session.add(PortfolioVersionRow(portfolio_id="default", version=0))
        session.add(
            PortfolioSnapshotProjectionRow(
                portfolio_id="default",
                as_of_time=E2E_BACKTEST_START,
                cash="100000",
                equity="100000",
            )
        )
        StrictPitIngestor(session).ingest(bundle)
        session.flush()
        authority = SqlPitCertificateAuthority(session, settings.pit_approval_secret)
        bundle_set_hash = bundle_set_hash_for(session, E2E_BACKTEST_START.date())
        for report_id, scope in certificate_scopes:
            report = PitAuditReportRow(
                id=report_id,
                passed=True,
                coverage_start=E2E_BACKTEST_START.date(),
                coverage_end=E2E_BACKTEST_START.date(),
                market_id=scope.market_id,
                universe_id=scope.universe_id,
                bundle_set_hash=bundle_set_hash,
                audit_hash=sha256(report_id.encode("utf-8")).hexdigest(),
                verified_at=certified_as_of,
            )
            session.add(report)
            session.flush()
            authority.approve(
                report.id,
                as_of_time=certified_as_of,
                scope=scope,
            )
        session.commit()


def _fixture_root() -> Path:
    return Path(__file__).parents[2] / "tests" / "fixtures" / "pit_bundle"
