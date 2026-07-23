"""Low-rate CNINFO web disclosure client for local holding-analysis refreshes.

CNINFO's web endpoint is intentionally isolated here because it is not a licensed,
versioned data-service API.  It fetches only the current holding's periodic-report
metadata and individual attachments; callers remain fail-closed on any error.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from io import BytesIO
import re
from typing import Protocol
from urllib.parse import urlparse

from backend.app.infrastructure.market.holding_financial_evidence import (
    FinancialAnnouncementReference,
)


_LIST_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_ATTACHMENT_ROOT = "https://static.cninfo.com.cn/"
_SECURITY_DIRECTORY_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
_TIMEOUT_SECONDS = 12.0
_CATEGORIES = (
    "category_ndbg_szsh",
    "category_bndbg_szsh",
    "category_yjdbg_szsh",
    "category_sjdbg_szsh",
)
_UNWANTED_TITLE_MARKERS = ("摘要", "英文", "更正", "提示性公告")
_YEAR_PATTERN = re.compile(r"(?P<year>20\d{2})年")
_TAG_PATTERN = re.compile(r"<[^>]+>")
_REPORT_TITLE_SUFFIX = re.compile(
    r"\s*20\d{2}\s*年(?:第一季度|半年度|第三季度|年度)报告.*$"
)


class HttpResponse(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, object]: ...


class HttpSession(Protocol):
    def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        timeout: float,
        headers: dict[str, str],
    ) -> HttpResponse: ...

    def get(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str],
    ) -> HttpResponse: ...


class CninfoFinancialAnnouncementClient:
    """Fetch full A-share periodic reports from the CNINFO disclosure website."""

    def __init__(
        self,
        *,
        session: HttpSession,
        pdf_text: Callable[[bytes], str] | None = None,
    ) -> None:
        self._session = session
        self._pdf_text = pdf_text or _extract_pdf_text
        self._securities: dict[str, tuple[str, str]] | None = None

    def list_financial_announcements(
        self,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[FinancialAnnouncementReference, ...]:
        _require_aware(as_of_time)
        code, column = _cninfo_security(security_id)
        org_id, issuer = self._security_metadata(code)
        stock = f"{code},{org_id}"
        found: dict[tuple[date, str], FinancialAnnouncementReference] = {}
        for category in _CATEGORIES:
            response = self._post_list(
                {
                    "pageNum": "1",
                    "pageSize": "30",
                    "column": column,
                    "tabName": "fulltext",
                    "plate": "",
                    "stock": stock,
                    "searchkey": "",
                    "secid": "",
                    "category": category,
                    "trade": "",
                    "seDate": "",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                }
            )
            announcements = response.json().get("announcements", ())
            if not isinstance(announcements, list):
                continue
            for item in announcements:
                if not isinstance(item, dict):
                    continue
                reference = _reference_from_row(security_id, issuer, item, as_of_time)
                if reference is not None:
                    found[(reference.report_period, reference.source_url)] = reference
        return tuple(sorted(found.values(), key=lambda item: item.report_period, reverse=True))

    def download_text(self, reference: FinancialAnnouncementReference) -> str:
        _validate_cninfo_attachment_url(reference.source_url)
        response = self._session.get(
            reference.source_url,
            timeout=_TIMEOUT_SECONDS,
            headers=_headers(),
        )
        response.raise_for_status()
        return self._pdf_text(response.content)

    def _post_list(self, data: dict[str, str]) -> HttpResponse:
        failure: Exception | None = None
        for _ in range(2):
            try:
                response = self._session.post(
                    _LIST_URL,
                    data=data,
                    timeout=_TIMEOUT_SECONDS,
                    headers=_headers(),
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                failure = exc
        assert failure is not None
        raise failure

    def _security_metadata(self, code: str) -> tuple[str, str]:
        if self._securities is None:
            response = self._session.get(
                _SECURITY_DIRECTORY_URL,
                timeout=_TIMEOUT_SECONDS,
                headers=_headers(),
            )
            response.raise_for_status()
            rows = response.json().get("stockList", ())
            if not isinstance(rows, list):
                raise RuntimeError("CNINFO security directory has an invalid response")
            self._securities = {
                str(item.get("code")): (
                    str(item.get("orgId")),
                    _clean_title(item.get("zwjc")),
                )
                for item in rows
                if isinstance(item, dict)
                and str(item.get("code", "")).isdigit()
                and str(item.get("orgId", "")).strip()
            }
        security = self._securities.get(code)
        if security is None:
            raise RuntimeError(f"CNINFO security directory has no organization id for {code}")
        return security


def _reference_from_row(
    security_id: str,
    fallback_issuer: str,
    row: dict[str, object],
    as_of_time: datetime,
) -> FinancialAnnouncementReference | None:
    title = _clean_title(row.get("announcementTitle"))
    if not _is_full_periodic_report(title):
        return None
    published_at = _announcement_time(row.get("announcementTime"), as_of_time)
    if published_at is None or published_at > as_of_time:
        return None
    report_period = _report_period(title)
    adjunct_url = row.get("adjunctUrl")
    if report_period is None or not isinstance(adjunct_url, str) or not adjunct_url.strip():
        return None
    source_url = _ATTACHMENT_ROOT + adjunct_url.lstrip("/")
    _validate_cninfo_attachment_url(source_url)
    issuer = (
        _clean_title(row.get("secName"))
        or _issuer_from_title(title)
        or fallback_issuer
        or security_id
    )
    return FinancialAnnouncementReference(
        security_id=security_id,
        report_period=report_period,
        issuer=issuer,
        title=title,
        published_at=published_at,
        source_url=source_url,
    )


def _cninfo_security(security_id: str) -> tuple[str, str]:
    code, separator, exchange = security_id.upper().partition(".")
    if separator != "." or len(code) != 6 or not code.isdigit() or exchange not in {"SH", "SZ"}:
        raise ValueError(f"invalid A-share security id: {security_id}")
    return code, "sse" if exchange == "SH" else "szse"


def _clean_title(value: object) -> str:
    return _TAG_PATTERN.sub("", str(value or "")).strip()


def _is_full_periodic_report(title: str) -> bool:
    if not title or any(marker in title for marker in _UNWANTED_TITLE_MARKERS):
        return False
    return any(marker in title for marker in ("年度报告", "半年度报告", "第一季度报告", "第三季度报告"))


def _report_period(title: str) -> date | None:
    match = _YEAR_PATTERN.search(title)
    if match is None:
        return None
    year = int(match.group("year"))
    if "第一季度报告" in title:
        return date(year, 3, 31)
    if "半年度报告" in title:
        return date(year, 6, 30)
    if "第三季度报告" in title:
        return date(year, 9, 30)
    if "年度报告" in title:
        return date(year, 12, 31)
    return None


def _issuer_from_title(title: str) -> str:
    before_separator = title.split("：", maxsplit=1)[0].strip()
    if before_separator != title:
        return before_separator
    return _REPORT_TITLE_SUFFIX.sub("", title).strip()


def _announcement_time(value: object, as_of_time: datetime) -> datetime | None:
    try:
        milliseconds = int(str(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).astimezone(as_of_time.tzinfo)


def _validate_cninfo_attachment_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname != "static.cninfo.com.cn":
        raise ValueError("financial attachment URL must be an official CNINFO HTTPS URL")


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.cninfo.com.cn",
        "Referer": "https://www.cninfo.com.cn/",
        "User-Agent": "DA-local-holding-analysis/0.1",
    }


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required to extract official announcement text") from exc
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of_time must be timezone-aware")
