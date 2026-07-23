from datetime import date, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.market.pit_models import DataKind, SnapshotScope
from backend.app.infrastructure.market.official_evidence import (
    OfficialEvidenceDocument,
    OfficialEvidenceSource,
    OfficialEvidenceStore,
)
from backend.app.infrastructure.market.research_warehouse import ResearchPointInTimeWarehouse
from backend.app.infrastructure.market.build import build_point_in_time_warehouse
from backend.app.infrastructure.persistence.official_evidence_rows import OfficialEvidenceRow


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 23, 10, 0, tzinfo=SHANGHAI)


def _document(**overrides: object) -> OfficialEvidenceDocument:
    values: dict[str, object] = {
        "kind": "financial_announcement",
        "source_url": "https://www.szse.cn/disclosure/listed/notice/index.html",
        "content_sha256": sha256(b"official disclosure").hexdigest(),
        "published_at": datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
        "first_observed_at": datetime(2026, 4, 29, 20, 5, tzinfo=SHANGHAI),
        "reviewed_at": datetime(2026, 4, 30, 9, 0, tzinfo=SHANGHAI),
        "security_id": "000568.SZ",
        "report_period": date(2026, 3, 31),
        "title": "2026 年第一季度报告",
        "text": "official disclosure text",
    }
    values.update(overrides)
    return OfficialEvidenceDocument(**values)


def test_import_rejects_non_official_source_url() -> None:
    store = OfficialEvidenceStore.in_memory()

    with pytest.raises(ValueError, match="official allowlist"):
        store.import_document(_document(source_url="https://example.com/report"))


def test_holding_source_returns_reviewed_financial_and_policy_evidence_only_when_available() -> None:
    store = OfficialEvidenceStore.in_memory()
    financial = _document()
    policy = _document(
        kind="policy_document",
        source_url="https://www.csrc.gov.cn/csrc/c100028/c123/content.shtml",
        security_id=None,
        report_period=None,
        title="监管政策",
        text="official policy text",
        content_sha256=sha256(b"official policy").hexdigest(),
    )
    store.import_document(financial)
    store.import_document(policy)

    batch = OfficialEvidenceSource(store).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope.holding_analysis(("000568.SZ",)),
    )

    assert {record.kind for record in batch.records} == {
        DataKind.FINANCIAL_DISCLOSURE,
        DataKind.POLICY_DOCUMENT,
    }
    assert {record.source_artifact_hash for record in batch.records} == {
        financial.content_sha256,
        policy.content_sha256,
    }


def test_holding_source_fails_closed_for_unreviewed_or_future_evidence() -> None:
    store = OfficialEvidenceStore.in_memory()
    store.import_document(_document(reviewed_at=AS_OF.replace(hour=11)))

    batch = OfficialEvidenceSource(store).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope.holding_analysis(("000568.SZ",)),
    )

    assert batch.records == ()


def test_empty_official_store_keeps_holding_financial_disclosure_fail_closed() -> None:
    snapshot = ResearchPointInTimeWarehouse(
        (OfficialEvidenceSource(OfficialEvidenceStore.in_memory()),)
    ).snapshot(
        as_of_time=AS_OF,
        scope=SnapshotScope.holding_analysis(("000568.SZ",)),
    )

    assert any(
        issue.code == "REQUIRED_DATASET_MISSING"
        and issue.dataset == DataKind.FINANCIAL_DISCLOSURE.value
        and issue.entity_id == "000568.SZ"
        for issue in snapshot.quality.issues
    )


def test_research_builder_accepts_official_evidence_provider_seam() -> None:
    class Market:
        pass

    class Policy:
        pass

    class Llm:
        pass

    store = OfficialEvidenceStore.in_memory()
    warehouse = build_point_in_time_warehouse(
        market=Market(),
        policy=Policy(),
        llm=Llm(),
        official_evidence=store,
    )

    assert any(
        isinstance(source, OfficialEvidenceSource)
        for source in warehouse.sources[0].sources
    )


def test_sql_store_round_trips_only_reviewed_official_evidence() -> None:
    engine = create_engine("sqlite://")
    OfficialEvidenceRow.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    store = OfficialEvidenceStore(sessions)
    document = _document()

    store.import_document(document)

    assert store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",)) == (document,)
