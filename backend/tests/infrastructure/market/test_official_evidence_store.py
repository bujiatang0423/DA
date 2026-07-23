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
from backend.app.infrastructure.market.research_adapters import MarketEvidenceSource
from backend.app.infrastructure.market.research_adapters import LlmEvidenceSource
from backend.app.infrastructure.persistence.official_evidence_rows import OfficialEvidenceRow
from backend.app.ports.research_data import FinancialMaterial
from backend.app.ports.llm_factor import StructuredLlmFactor


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 23, 10, 0, tzinfo=SHANGHAI)


def _document(**overrides: object) -> OfficialEvidenceDocument:
    values: dict[str, object] = {
        "kind": "financial_announcement",
        "source_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "content_sha256": "untrusted-supplied-hash",
        "published_at": datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
        "first_observed_at": datetime(2026, 4, 29, 20, 5, tzinfo=SHANGHAI),
        "reviewed_at": datetime(2026, 4, 30, 9, 0, tzinfo=SHANGHAI),
        "security_id": "000568.SZ",
        "report_period": date(2026, 3, 31),
        "issuer": "泸州老窖股份有限公司",
        "effective_at": datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
        "security_ids": (),
        "title": "2026 年第一季度报告",
        "text": "official disclosure text",
    }
    values.update(overrides)
    return OfficialEvidenceDocument(**values)


def test_import_rejects_non_official_source_url() -> None:
    store = OfficialEvidenceStore.in_memory()

    with pytest.raises(ValueError, match="official allowlist"):
        store.import_document(_document(source_url="https://example.com/report"))


def test_import_accepts_cninfo_and_recomputes_untrusted_content_hash() -> None:
    store = OfficialEvidenceStore.in_memory()
    document = _document()

    store.import_document(document)

    persisted = store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",))[0]
    assert persisted.content_sha256 == sha256(document.text.encode()).hexdigest()


def test_financial_and_policy_allowlists_are_separate() -> None:
    store = OfficialEvidenceStore.in_memory()

    with pytest.raises(ValueError, match="financial announcement"):
        store.import_document(
            _document(source_url="https://www.csrc.gov.cn/csrc/c100028/c123/content.shtml")
        )
    with pytest.raises(ValueError, match="policy document"):
        store.import_document(
            _document(
                kind="policy_document",
                security_id=None,
                report_period=None,
                issuer="中国证监会",
                security_ids=("000568.SZ",),
            )
        )


def test_import_rejects_review_before_first_observation() -> None:
    store = OfficialEvidenceStore.in_memory()

    with pytest.raises(ValueError, match="reviewed_at"):
        store.import_document(
            _document(reviewed_at=datetime(2026, 4, 29, 20, 4, tzinfo=SHANGHAI))
        )


def test_policy_requires_holding_security_bindings_and_effective_time() -> None:
    store = OfficialEvidenceStore.in_memory()

    with pytest.raises(ValueError, match="security_ids"):
        store.import_document(
            _document(
                kind="policy_document",
                security_id=None,
                report_period=None,
                issuer="中国证监会",
                security_ids=(),
                source_url="https://www.csrc.gov.cn/csrc/c100028/c123/content.shtml",
            )
        )


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
        issuer="中国证监会",
        security_ids=("000568.SZ",),
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
        sha256(financial.text.encode()).hexdigest(),
        sha256(policy.text.encode()).hexdigest(),
    }
    policy_record = next(record for record in batch.records if record.kind is DataKind.POLICY_DOCUMENT)
    assert policy_record.entity_id == "000568.SZ"


def test_review_time_is_audit_metadata_not_point_in_time_availability() -> None:
    store = OfficialEvidenceStore.in_memory()
    store.import_document(_document(reviewed_at=AS_OF.replace(hour=11)))

    batch = OfficialEvidenceSource(store).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope.holding_analysis(("000568.SZ",)),
    )

    assert len(batch.records) == 1


def test_holding_source_fails_closed_for_future_publication_or_effective_time() -> None:
    store = OfficialEvidenceStore.in_memory()
    store.import_document(_document(effective_at=AS_OF.replace(hour=11)))

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

    persisted = store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",))
    assert len(persisted) == 1
    assert persisted[0].content_sha256 == sha256(document.text.encode()).hexdigest()


def test_akshare_financial_facts_require_matching_official_announcement() -> None:
    class Market:
        def financials(
            self, security_id: str, as_of_time: datetime
        ) -> tuple[FinancialMaterial, ...]:
            del as_of_time
            return (
                FinancialMaterial(
                    security_id,
                    date(2026, 3, 31),
                    datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
                    {"revenue": 100},
                    "akshare-hash",
                ),
            )

    store = OfficialEvidenceStore.in_memory()
    store.import_document(_document())
    batch = MarketEvidenceSource(Market(), official_evidence=store).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope(
            security_ids=("000568.SZ",),
            required_kinds=(DataKind.FINANCIAL_FACT,),
        ),
    )

    assert len(batch.records) == 1
    assert batch.records[0].source_artifact_hash == sha256(b"official disclosure text").hexdigest()
    assert batch.records[0].payload["official_evidence_hash"] == batch.records[0].source_artifact_hash


def test_akshare_financial_facts_fail_closed_without_matching_official_announcement() -> None:
    class Market:
        def financials(
            self, security_id: str, as_of_time: datetime
        ) -> tuple[FinancialMaterial, ...]:
            del as_of_time
            return (
                FinancialMaterial(
                    security_id,
                    date(2026, 3, 31),
                    datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
                    {"revenue": 100},
                    "akshare-hash",
                ),
            )

    batch = MarketEvidenceSource(
        Market(), official_evidence=OfficialEvidenceStore.in_memory()
    ).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope(
            security_ids=("000568.SZ",),
            required_kinds=(DataKind.FINANCIAL_FACT,),
        ),
    )

    assert batch.records == ()


def test_llm_source_consumes_only_persisted_official_policy_and_financial_evidence() -> None:
    class Market:
        def financials(
            self, security_id: str, as_of_time: datetime
        ) -> tuple[FinancialMaterial, ...]:
            del as_of_time
            return (
                FinancialMaterial(
                    security_id,
                    date(2026, 3, 31),
                    datetime(2026, 4, 29, 20, 0, tzinfo=SHANGHAI),
                    {"revenue": 100},
                    "akshare-hash",
                ),
            )

    class Policy:
        def materials(self, *, as_of_time: datetime) -> tuple[object, ...]:
            raise AssertionError("live policy provider must not reach the LLM evidence path")

    captured: dict[str, object] = {}

    class Llm:
        def extract(self, **kwargs: object) -> StructuredLlmFactor:
            captured.update(kwargs)
            policy_hash = kwargs["policy_materials"][0].content_hash  # type: ignore[index]
            payload = {
                "policy_direction": "neutral",
                "implementation_stage": "planning",
                "financial_light": "unknown",
                "policy_strength": 50,
                "policy_relevance": 50,
                "financial_text_score": 50,
                "llm_confidence": 0.5,
                "evidence_confidence": 0.5,
                "data_completeness": 0.5,
                "red_flags": [],
                "evidence": [
                    {
                        "source_id": policy_hash,
                        "published_at": AS_OF.isoformat(),
                        "quote": "official policy",
                    }
                ],
            }
            return StructuredLlmFactor(
                AS_OF, "000568.SZ", "m", "prompt", "input", "output", payload
            )

    store = OfficialEvidenceStore.in_memory()
    store.import_document(_document())
    store.import_document(
        _document(
            kind="policy_document",
            security_id=None,
            report_period=None,
            issuer="中国证监会",
            security_ids=("000568.SZ",),
            source_url="https://www.csrc.gov.cn/csrc/c100028/c123/content.shtml",
            title="政策",
            text="policy text",
        )
    )

    LlmEvidenceSource(Llm(), Policy(), Market(), official_evidence=store).fetch(
        as_of_time=AS_OF,
        scope=SnapshotScope(("000568.SZ",)),
    )

    financial = captured["financial_materials"][0]  # type: ignore[index]
    assert financial.source_hash == sha256(b"official disclosure text").hexdigest()
    assert captured["policy_materials"][0].content_hash == sha256(b"policy text").hexdigest()  # type: ignore[index]
