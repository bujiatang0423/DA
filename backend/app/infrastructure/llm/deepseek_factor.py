import hashlib
import json
from datetime import UTC, datetime
from collections.abc import Mapping, Sequence

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
    if _contains_forbidden_field(payload):
        raise LlmFactorValidationError("forbidden output fields")
    for f, a in ENUMS.items():
        if payload.get(f) not in a:
            raise LlmFactorValidationError(f"invalid enum: {f}")
    for f in ("policy_strength", "policy_relevance", "financial_text_score"):
        if not _is_number(payload.get(f)) or not 0 <= payload[f] <= 100:
            raise LlmFactorValidationError(f"invalid score: {f}")
    for f in ("llm_confidence", "evidence_confidence", "data_completeness"):
        if not _is_number(payload.get(f)) or not 0 <= payload[f] <= 1:
            raise LlmFactorValidationError(f"invalid confidence: {f}")
    if not isinstance(payload.get("red_flags"), list):
        raise LlmFactorValidationError("red_flags must be a list")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise LlmFactorValidationError("evidence is required")
    for item in evidence:
        if not isinstance(item, dict) or not str(item.get("quote", "")).strip():
            raise LlmFactorValidationError("evidence quote is required")
        published_at = _parse_available_time(item.get("published_at"))
        if item.get("source_id") not in allowed_evidence or published_at > _as_utc(as_of_time):
            raise LlmFactorValidationError("evidence is unavailable")
    return payload


def _contains_forbidden_field(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in FORBIDDEN_FIELDS or _contains_forbidden_field(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_available_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise LlmFactorValidationError("evidence published_at is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LlmFactorValidationError("evidence published_at is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LlmFactorValidationError("evidence published_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LlmFactorValidationError("as_of_time must be timezone-aware")
    return value.astimezone(UTC)


def content_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()
