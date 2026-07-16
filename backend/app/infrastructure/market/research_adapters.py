from dataclasses import asdict
from datetime import datetime, date, time
from backend.app.core.market.pit_models import DataKind, LineageRef, SnapshotScope, TemporalRecord
from backend.app.infrastructure.market.research_source import ResearchBatch

class MarketEvidenceSource:
    provider = "research_market"
    def __init__(self, market: object, benchmark_ids: tuple[str, ...] = ()) -> None:
        self.market, self.benchmark_ids = market, benchmark_ids
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        if hasattr(self.market, "research_records"):
            result = tuple(self.market.research_records(as_of_time=as_of_time, scope=scope))
            return ResearchBatch(result, _lineage(self.provider, result))
        result: list[TemporalRecord] = []
        ids = scope.security_ids or tuple(x.security_id for x in self.market.universe(as_of_time))
        for sid in ids:
            for bar in self.market.daily_bars(sid, as_of_time):
                event = datetime.combine(bar.trade_date, time(15, 0), as_of_time.tzinfo) if isinstance(bar.trade_date, date) else bar.trade_date
                result.append(_record(DataKind.DAILY_BAR_RAW, sid, str(bar.trade_date), event, getattr(bar, "available_at", as_of_time), bar.source_hash, asdict(bar)))
        return ResearchBatch(tuple(result), _lineage(self.provider, tuple(result)))

def _record(kind: DataKind, entity: str, suffix: str, event: datetime, available: datetime, h: str, payload: dict[str, object]) -> TemporalRecord:
    return TemporalRecord(f"{kind.value}:{entity}:{suffix}", kind, entity, event, event, available, h, payload)

def _lineage(provider: str, records: tuple[TemporalRecord, ...]) -> tuple[LineageRef, ...]:
    return tuple(LineageRef(f"{provider}-{h[:16]}", provider, h) for h in sorted({r.source_artifact_hash for r in records}))

class PolicyEvidenceSource:
    provider = "official_policy"
    def __init__(self, policy: object) -> None: self.policy = policy
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        del scope
        rows = []
        for item in self.policy.materials(as_of_time=as_of_time):
            available = max(item.published_at, item.first_observed_at)
            if available > as_of_time: continue
            rows.append(_record(DataKind.POLICY_DOCUMENT, "MARKET:POLICY", item.source_id, item.published_at, available, item.content_hash, asdict(item)))
        result = tuple(rows)
        return ResearchBatch(result, _lineage(self.provider, result))

class LlmEvidenceSource:
    provider = "structured_llm_factor"
    def __init__(self, llm: object, policy: object, market: object) -> None: self.llm, self.policy, self.market = llm, policy, market
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        policies = tuple(x for x in self.policy.materials(as_of_time=as_of_time) if max(x.published_at, x.first_observed_at) <= as_of_time)
        ids = scope.security_ids or tuple(x.security_id for x in self.market.universe(as_of_time))
        rows = []
        for sid in ids:
            financials = tuple(x for x in self.market.financials(sid, as_of_time) if x.published_at <= as_of_time)
            factor = self.llm.extract(as_of_time=as_of_time, security_id=sid, policy_materials=policies, financial_materials=financials)
            if factor.as_of_time != as_of_time or factor.security_id != sid: raise ValueError("LLM factor identity mismatch")
            rows.append(_record(DataKind.LLM_FACTOR, sid, factor.output_hash, factor.as_of_time, factor.as_of_time, factor.output_hash, {"model_id": factor.model_id, "prompt_hash": factor.prompt_hash, "input_hash": factor.input_hash, "output_hash": factor.output_hash, "factor": factor.payload}))
        result = tuple(rows)
        return ResearchBatch(result, _lineage(self.provider, result))

class ResearchEvidenceSource:
    provider = "research_evidence"
    def __init__(self, sources: tuple[object, ...]) -> None: self.sources = sources
    def fetch(self, *, as_of_time: datetime, scope: SnapshotScope) -> ResearchBatch:
        batches = tuple(s.fetch(as_of_time=as_of_time, scope=scope) for s in self.sources)
        records = tuple(r for b in batches for r in b.records)
        missing = set(scope.required_kinds) - {r.kind for r in records}
        if missing: raise ValueError("research evidence source missing: " + ",".join(sorted(x.value for x in missing)))
        return ResearchBatch(records, tuple(l for b in batches for l in b.lineage))
