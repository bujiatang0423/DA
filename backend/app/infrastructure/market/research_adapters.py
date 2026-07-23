from dataclasses import asdict
from datetime import datetime, date, time

from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.llm.deepseek_factor import validate_factor
from backend.app.infrastructure.market.official_evidence import (
    FINANCIAL_ANNOUNCEMENT,
    POLICY_DOCUMENT as OFFICIAL_POLICY_DOCUMENT,
    OfficialEvidenceDocument,
    OfficialEvidenceReader,
)
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial
from backend.app.infrastructure.market.research_source import ResearchBatch


class MarketEvidenceSource:
    provider = "research_market"

    def __init__(
        self,
        market: object,
        benchmark_ids: tuple[str, ...] = (),
        official_evidence: OfficialEvidenceReader | None = None,
    ) -> None:
        self.market, self.benchmark_ids = market, benchmark_ids
        self._official_evidence = official_evidence
        provider_name = getattr(market, "provider_name", self.provider)
        if isinstance(provider_name, str) and provider_name:
            self.provider = provider_name

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        if hasattr(self.market, "research_records"):
            allowed_ids = set(scope.security_ids)
            required = set(scope.required_kinds)
            result = tuple(
                record
                for record in self.market.research_records(as_of_time=as_of_time, scope=scope)
                if record.event_time <= as_of_time and record.available_at <= as_of_time
                and (not allowed_ids or record.entity_id in allowed_ids)
                and (not required or record.kind in required)
            )
            return ResearchBatch(result, _lineage(self.provider, result))
        if not scope.security_ids and self.provider == "akshare":
            return ResearchBatch((), ())
        result: list[TemporalRecord] = []
        ids = scope.security_ids or tuple(x.security_id for x in self.market.universe(as_of_time))
        required = set(scope.required_kinds)
        include_bars = not required or DataKind.DAILY_BAR_RAW in required
        include_financials = not required or bool(
            {DataKind.FINANCIAL_DISCLOSURE, DataKind.FINANCIAL_FACT} & required
        )
        official_financials = _official_financials(
            self._official_evidence,
            as_of_time=as_of_time,
            security_ids=ids,
        )
        for sid in ids:
            if include_bars:
                for bar in self.market.daily_bars(sid, as_of_time):
                    available_at = getattr(bar, "available_at", as_of_time)
                    if available_at > as_of_time:
                        continue
                    event = (
                        datetime.combine(bar.trade_date, time(15, 0), as_of_time.tzinfo)
                        if isinstance(bar.trade_date, date)
                        else bar.trade_date
                    )
                    result.append(
                        _record(
                            DataKind.DAILY_BAR_RAW,
                            sid,
                            str(bar.trade_date),
                            event,
                            available_at,
                            bar.source_hash,
                            asdict(bar),
                        )
                    )
            if include_financials:
                for financial in self.market.financials(sid, as_of_time):
                    if financial.published_at > as_of_time:
                        continue
                    official = official_financials.get((sid, financial.report_period))
                    if self._official_evidence is not None and official is None:
                        continue
                    if not required or DataKind.FINANCIAL_DISCLOSURE in required:
                        if official is None:
                            result.append(
                                _record(
                                    DataKind.FINANCIAL_DISCLOSURE,
                                    sid,
                                    financial.report_period.isoformat(),
                                    financial.published_at,
                                    financial.published_at,
                                    financial.source_hash,
                                    asdict(financial),
                                )
                            )
                    if not required or DataKind.FINANCIAL_FACT in required:
                        for metric, value in financial.facts.items():
                            published_at = official.published_at if official else financial.published_at
                            available_at = (
                                max(official.published_at, official.first_observed_at)
                                if official
                                else financial.published_at
                            )
                            source_hash = official.content_sha256 if official else financial.source_hash
                            payload: dict[str, object] = {"metric": metric, "value": value}
                            if official:
                                payload.update(
                                    {
                                        "official_evidence_hash": official.content_sha256,
                                        "official_source_url": official.source_url,
                                        "published_at": official.published_at.isoformat(),
                                    }
                                )
                            result.append(
                                _record(
                                    DataKind.FINANCIAL_FACT,
                                    sid,
                                    f"{financial.report_period.isoformat()}:{metric}",
                                    published_at,
                                    available_at,
                                    source_hash,
                                    payload,
                                )
                            )
        return ResearchBatch(tuple(result), _lineage(self.provider, tuple(result)))


def _record(
    kind: DataKind,
    entity: str,
    suffix: str,
    event: datetime,
    available: datetime,
    h: str,
    payload: dict[str, object],
) -> TemporalRecord:
    return TemporalRecord(
        f"{kind.value}:{entity}:{suffix}", kind, entity, event, event, available, h, payload
    )


def _lineage(provider: str, records: tuple[TemporalRecord, ...]) -> tuple[LineageRef, ...]:
    return _lineage_from_hashes(provider, {r.source_artifact_hash for r in records})


def _official_financials(
    evidence: OfficialEvidenceReader | None,
    *,
    as_of_time: datetime,
    security_ids: tuple[str, ...],
) -> dict[tuple[str, date], OfficialEvidenceDocument]:
    if evidence is None:
        return {}
    return {
        (document.security_id, document.report_period): document
        for document in evidence.documents(as_of_time=as_of_time, security_ids=security_ids)
        if document.kind == FINANCIAL_ANNOUNCEMENT
        and document.security_id is not None
        and document.report_period is not None
    }


def _llm_financials(
    market: object,
    security_id: str,
    as_of_time: datetime,
    official_documents: tuple[OfficialEvidenceDocument, ...],
    require_official_evidence: bool,
) -> tuple[FinancialMaterial, ...]:
    documents_by_period = {
        (document.security_id, document.report_period): document
        for document in official_documents
        if document.kind == FINANCIAL_ANNOUNCEMENT
    }
    materials: list[FinancialMaterial] = []
    for financial in market.financials(security_id, as_of_time):
        if financial.published_at > as_of_time:
            continue
        document = documents_by_period.get((security_id, financial.report_period))
        if require_official_evidence and document is None:
            continue
        if document is None:
            materials.append(financial)
            continue
        materials.append(
            FinancialMaterial(
                security_id=financial.security_id,
                report_period=financial.report_period,
                published_at=document.published_at,
                facts=financial.facts,
                source_hash=document.content_sha256,
            )
        )
    return tuple(materials)


def _lineage_from_hashes(provider: str, hashes: set[str]) -> tuple[LineageRef, ...]:
    return tuple(LineageRef(f"{provider}-{h[:16]}", provider, h) for h in sorted(hashes))


def _merge_lineage(
    first: tuple[LineageRef, ...], second: tuple[LineageRef, ...]
) -> tuple[LineageRef, ...]:
    return tuple(
        sorted(
            set(first) | set(second),
            key=lambda item: (item.source_artifact_hash, item.provider, item.batch_id),
        )
    )


class PolicyEvidenceSource:
    provider = "official_policy"

    def __init__(self, policy: object) -> None:
        self.policy = policy

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        del scope
        rows = []
        for item in self.policy.materials(as_of_time=as_of_time):
            available = max(item.published_at, item.first_observed_at)
            if available > as_of_time:
                continue
            rows.append(
                _record(
                    DataKind.POLICY_DOCUMENT,
                    "MARKET:POLICY",
                    item.source_id,
                    item.published_at,
                    available,
                    item.content_hash,
                    asdict(item),
                )
            )
        result = tuple(rows)
        return ResearchBatch(result, _lineage(self.provider, result))


class LlmEvidenceSource:
    provider = "structured_llm_factor"

    def __init__(
        self,
        llm: object,
        policy: object,
        market: object,
        official_evidence: OfficialEvidenceReader | None = None,
    ) -> None:
        self.llm, self.policy, self.market = llm, policy, market
        self._official_evidence = official_evidence

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        ids = scope.security_ids or tuple(x.security_id for x in self.market.universe(as_of_time))
        official_documents = (
            self._official_evidence.documents(as_of_time=as_of_time, security_ids=ids)
            if self._official_evidence is not None
            else ()
        )
        policies = (
            tuple(
                PolicyMaterial(
                    source_id=document.content_sha256,
                    published_at=document.published_at,
                    first_observed_at=document.first_observed_at,
                    evidence_grade="A",
                    content_hash=document.content_sha256,
                    text=document.text,
                )
                for document in official_documents
                if document.kind == OFFICIAL_POLICY_DOCUMENT
            )
            if self._official_evidence is not None
            else tuple(
                x
                for x in self.policy.materials(as_of_time=as_of_time)
                if max(x.published_at, x.first_observed_at) <= as_of_time
            )
        )
        rows = []
        input_hashes: set[str] = set()
        for sid in ids:
            financials = _llm_financials(
                self.market,
                sid,
                as_of_time,
                official_documents,
                self._official_evidence is not None,
            )
            factor = self.llm.extract(
                as_of_time=as_of_time,
                security_id=sid,
                policy_materials=policies,
                financial_materials=financials,
            )
            if factor.as_of_time != as_of_time or factor.security_id != sid:
                raise ValueError("LLM factor identity mismatch")
            if not all(
                isinstance(getattr(factor, field, None), str)
                and bool(getattr(factor, field).strip())
                for field in ("model_id", "prompt_hash", "input_hash", "output_hash")
            ) or not isinstance(factor.payload, dict):
                raise ValueError("LLM factor metadata/schema mismatch")
            validate_factor(
                factor.payload,
                as_of_time=as_of_time,
                allowed_evidence={item.source_id for item in policies}
                | {item.source_hash for item in financials},
            )
            row_input_hashes = {item.content_hash for item in policies} | {
                item.source_hash for item in financials
            }
            input_hashes.update(row_input_hashes)
            rows.append(
                _record(
                    DataKind.LLM_FACTOR,
                    sid,
                    factor.output_hash,
                    factor.as_of_time,
                    factor.as_of_time,
                    factor.output_hash,
                    {
                        "model_id": factor.model_id,
                        "prompt_hash": factor.prompt_hash,
                        "input_hash": factor.input_hash,
                        "output_hash": factor.output_hash,
                        "input_artifact_hashes": tuple(sorted(row_input_hashes)),
                        "factor": factor.payload,
                    },
                )
            )
        result = tuple(rows)
        return ResearchBatch(
            result,
            _merge_lineage(
                _lineage(self.provider, result),
                _lineage_from_hashes(self.provider, input_hashes),
            ),
        )


class ResearchEvidenceSource:
    provider = "research_evidence"

    def __init__(self, sources: tuple[object, ...]) -> None:
        self.sources = sources

    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        batches = tuple(s.fetch(as_of_time=as_of_time, scope=scope) for s in self.sources)
        records_by_id: dict[str, TemporalRecord] = {}
        for batch in batches:
            for record in batch.records:
                previous = records_by_id.get(record.record_id)
                if previous is not None and previous != record:
                    raise ValueError(
                        f"conflicting record from research providers: {record.record_id}"
                    )
                records_by_id[record.record_id] = record
        records = tuple(records_by_id[record_id] for record_id in sorted(records_by_id))
        missing = set(scope.required_kinds) - {r.kind for r in records}
        if missing:
            raise ValueError(
                "research evidence source missing: " + ",".join(sorted(x.value for x in missing))
            )
        lineage = tuple(
            sorted(
                {item for batch in batches for item in batch.lineage},
                key=lambda item: (
                    item.source_artifact_hash,
                    item.provider,
                    item.batch_id,
                ),
            )
        )
        return ResearchBatch(records, lineage)
