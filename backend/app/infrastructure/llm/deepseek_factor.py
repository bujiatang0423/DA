import hashlib
import json
from datetime import datetime

FORBIDDEN_FIELDS = frozenset({"action", "quantity", "position", "buy", "sell"})
ENUMS = {
    "policy_direction": {"supportive", "neutral", "restrictive", "unknown"},
    "implementation_stage": {"planning", "pilot", "execution", "mature", "exit", "unknown"},
    "financial_light": {"green", "yellow", "red", "unknown"},
}


class LlmFactorValidationError(ValueError):
    pass


def validate_factor(
    payload: dict[str, object], *, as_of_time: datetime, allowed_evidence: set[str]
) -> dict[str, object]:
    if FORBIDDEN_FIELDS.intersection(payload):
        raise LlmFactorValidationError("forbidden output fields")
    for f, a in ENUMS.items():
        if payload.get(f) not in a:
            raise LlmFactorValidationError(f"invalid enum: {f}")
    for f in ("policy_strength", "policy_relevance", "financial_text_score"):
        if not isinstance(payload.get(f), (int, float)) or not 0 <= payload[f] <= 100:
            raise LlmFactorValidationError(f"invalid score: {f}")
    for f in ("llm_confidence", "evidence_confidence", "data_completeness"):
        if not isinstance(payload.get(f), (int, float)) or not 0 <= payload[f] <= 1:
            raise LlmFactorValidationError(f"invalid confidence: {f}")
    if not isinstance(payload.get("red_flags"), list):
        raise LlmFactorValidationError("red_flags must be a list")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise LlmFactorValidationError("evidence is required")
    for item in evidence:
        if not isinstance(item, dict) or not str(item.get("quote", "")).strip():
            raise LlmFactorValidationError("evidence quote is required")
        if (
            item.get("source_id") not in allowed_evidence
            or datetime.fromisoformat(str(item["published_at"])) > as_of_time
        ):
            raise LlmFactorValidationError("evidence is unavailable")
    return payload


def content_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()
