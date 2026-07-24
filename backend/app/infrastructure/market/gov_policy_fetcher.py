"""Low-frequency importer for selected Chinese-government policy originals."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import re

from backend.app.infrastructure.market.official_evidence import (
    OfficialEvidenceDocument,
    OfficialEvidenceStore,
    POLICY_DOCUMENT,
)

FIFTEENTH_FIVE_YEAR_PLAN = "https://www.gov.cn/yaowen/liebiao/202603/content_7062633.htm"


class GovPolicyFetcher:
    def __init__(
        self, store: OfficialEvidenceStore, *, get: Callable[[str], str], now: Callable[[], datetime]
    ) -> None:
        self._store, self._get, self._now = store, get, now

    def refresh(self, *, security_ids: tuple[str, ...], as_of_time: datetime) -> None:
        observed_at = self._now()
        html = self._get(FIFTEENTH_FIVE_YEAR_PLAN)
        title = _tag_text(html, "h1", "ti")
        text = _tag_text(html, "div", "UCAP-CONTENT")
        published_at = _date(_meta(html, "others"), as_of_time)
        if not title or not text or published_at > as_of_time:
            return
        self._store.import_document(
            OfficialEvidenceDocument(
                kind=POLICY_DOCUMENT, source_url=FIFTEENTH_FIVE_YEAR_PLAN,
                content_sha256="calculated by OfficialEvidenceStore", published_at=published_at,
                first_observed_at=max(observed_at, published_at), reviewed_at=max(observed_at, published_at),
                security_id=None, report_period=None, issuer="中国政府网", effective_at=published_at,
                security_ids=security_ids, title=title, text=text,
            )
        )


def _meta(html: str, name: str) -> str:
    match = re.search(rf'<meta[^>]+name=["\']{name}["\'][^>]+content=["\']([^"\']+)', html)
    return match.group(1) if match else ""


def _tag_text(html: str, tag: str, identifier: str) -> str:
    match = re.search(rf'<{tag}[^>]+id=["\']{identifier}["\'][^>]*>(.*?)</{tag}>', html, re.S)
    return re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else ""


def _date(value: str, fallback: datetime) -> datetime:
    if not value:
        raise ValueError("official policy page is missing publication time")
    match = re.search(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}", value)
    if match is None:
        raise ValueError("official policy page has an invalid publication time")
    parsed = datetime.strptime(match.group(0), "%Y-%m-%d %H:%M")
    return parsed.replace(tzinfo=fallback.tzinfo)
