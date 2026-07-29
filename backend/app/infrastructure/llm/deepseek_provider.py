"""DeepSeek adapter that emits evidence-bound, non-trading factor payloads."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from backend.app.infrastructure.llm.deepseek_factor import content_hash, validate_factor
from backend.app.ports.llm_factor import StructuredLlmFactor
from backend.app.ports.policy import PolicyMaterial
from backend.app.ports.research_data import FinancialMaterial


class DeepSeekConfigurationError(RuntimeError):
    """Raised before a network call when the local API key is absent."""


class DeepSeekFactorProvider:
    """Call DeepSeek in JSON mode and reject any output outside the factor schema."""

    def __init__(
        self,
        *,
        api_key: str | None,
        post: Callable[..., object] | None = None,
        model: str = "deepseek-v4-pro",
        endpoint: str = "https://api.deepseek.com/chat/completions",
    ) -> None:
        self._api_key = api_key.strip() if api_key else ""
        self._post = post or _requests_post
        self._model = model
        self._endpoint = endpoint

    def extract(
        self,
        *,
        as_of_time: datetime,
        security_id: str,
        policy_materials: tuple[PolicyMaterial, ...],
        financial_materials: tuple[FinancialMaterial, ...],
    ) -> StructuredLlmFactor:
        if not self._api_key:
            raise DeepSeekConfigurationError("DeepSeek API key is not configured")
        input_payload = _input_payload(as_of_time, security_id, policy_materials, financial_materials)
        prompt = _prompt(input_payload)
        response = self._post(
            url=self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "response_format": {"type": "json_object"},
                "messages": (
                    {
                        "role": "system",
                        "content": "You only produce validated research factors, never trading advice.",
                    },
                    {"role": "user", "content": prompt},
                ),
                "temperature": 0,
            },
            timeout=30,
        )
        payload = _payload_from_response(response)
        allowed_evidence = {item.source_id for item in policy_materials} | {
            item.source_hash for item in financial_materials
        }
        validate_factor(payload, as_of_time=as_of_time, allowed_evidence=allowed_evidence)
        return StructuredLlmFactor(
            as_of_time=as_of_time,
            security_id=security_id,
            model_id=self._model,
            prompt_hash=content_hash(prompt),
            input_hash=content_hash(input_payload),
            output_hash=content_hash(payload),
            payload=payload,
        )


def _requests_post(**kwargs: object) -> object:
    import requests

    response = requests.post(**kwargs)
    response.raise_for_status()
    return response.json()


def _input_payload(
    as_of_time: datetime,
    security_id: str,
    policy_materials: tuple[PolicyMaterial, ...],
    financial_materials: tuple[FinancialMaterial, ...],
) -> dict[str, object]:
    return {
        "as_of_time": as_of_time.isoformat(),
        "security_id": security_id,
        "policies": tuple(
            {
                "source_id": item.source_id,
                "published_at": item.published_at.isoformat(),
                "text": item.text[:4000],
            }
            for item in policy_materials
        ),
        "financials": tuple(
            {
                "source_hash": item.source_hash,
                "report_period": item.report_period.isoformat(),
                "published_at": item.published_at.isoformat(),
                "facts": item.facts,
            }
            for item in financial_materials
        ),
    }


def _prompt(input_payload: Mapping[str, object]) -> str:
    schema = {
        "policy_direction": "supportive|neutral|restrictive|unknown",
        "implementation_stage": "planning|pilot|execution|mature|exit|unknown",
        "financial_light": "green|yellow|red|unknown",
        "policy_strength": "number 0..100",
        "policy_relevance": "number 0..100",
        "financial_text_score": "number 0..100",
        "llm_confidence": "number 0..1",
        "evidence_confidence": "number 0..1",
        "data_completeness": "number 0..1",
        "red_flags": "string[]",
        "evidence": "[{source_id,published_at,quote}]",
    }
    return json.dumps(
        {"input": input_payload, "required_schema": schema},
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )


def _payload_from_response(response: object) -> dict[str, object]:
    data = _as_mapping(response)
    try:
        choices = data["choices"]
        first = choices[0] if isinstance(choices, list) and choices else None
        content = _as_mapping(_as_mapping(first)["message"])["content"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("DeepSeek response does not contain a message") from error
    if not isinstance(content, str):
        raise ValueError("DeepSeek response content is not text")
    try:
        payload: Any = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("DeepSeek response is not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("DeepSeek response JSON must be an object")
    return payload


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("DeepSeek response has an invalid object")
    return value
