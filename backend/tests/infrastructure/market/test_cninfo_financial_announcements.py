from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.infrastructure.market.cninfo_financial_announcements import (
    CninfoFinancialAnnouncementClient,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 23, 16, 0, tzinfo=SHANGHAI)


class FakeResponse:
    def __init__(self, payload: dict[str, object] | None = None, content: bytes = b"") -> None:
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.posts: list[dict[str, str]] = []
        self.gets: list[str] = []

    def post(self, url: str, *, data: dict[str, str], timeout: float, headers: dict[str, str]) -> FakeResponse:
        del url, timeout, headers
        self.posts.append(data)
        return FakeResponse(
            {
                "announcements": [
                    {
                        "announcementTitle": "2026年第一季度报告",
                        "announcementTime": 1777305600000,
                        "adjunctUrl": "finalpage/2026-04-28/123456.pdf",
                    },
                    {
                        "announcementTitle": "泸州老窖：2026年第一季度报告摘要",
                        "announcementTime": 1777305600000,
                        "adjunctUrl": "finalpage/2026-04-28/summary.pdf",
                    },
                ]
            }
        )

    def get(self, url: str, *, timeout: float, headers: dict[str, str]) -> FakeResponse:
        del timeout, headers
        self.gets.append(url)
        if url.endswith("/new/data/szse_stock.json"):
            return FakeResponse(
                {
                    "stockList": [
                        {
                            "code": "000568",
                            "orgId": "9900000568",
                            "zwjc": "泸州老窖",
                        }
                    ]
                }
            )
        return FakeResponse(content=b"official pdf")


class OneFailureThenSuccessSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.post_attempts = 0

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.post_attempts += 1
        if self.post_attempts == 1:
            raise TimeoutError("transient CNINFO timeout")
        return super().post(*args, **kwargs)


def test_client_lists_full_periodic_report_and_excludes_summary_variants() -> None:
    session = FakeSession()
    client = CninfoFinancialAnnouncementClient(
        session=session,
        pdf_text=lambda content: content.decode("utf-8"),
    )

    references = client.list_financial_announcements(
        security_id="000568.SZ",
        as_of_time=AS_OF,
    )

    assert len(references) == 1
    assert references[0].report_period.isoformat() == "2026-03-31"
    assert references[0].issuer == "泸州老窖"
    assert references[0].source_url == "https://static.cninfo.com.cn/finalpage/2026-04-28/123456.pdf"
    assert {item["category"] for item in session.posts} == {
        "category_ndbg_szsh",
        "category_bndbg_szsh",
        "category_yjdbg_szsh",
        "category_sjdbg_szsh",
    }
    assert all(item["stock"] == "000568,9900000568" for item in session.posts)


def test_client_downloads_pdf_text_only_from_cninfo_attachment_url() -> None:
    session = FakeSession()
    client = CninfoFinancialAnnouncementClient(
        session=session,
        pdf_text=lambda content: content.decode("utf-8"),
    )
    reference = client.list_financial_announcements("000568.SZ", AS_OF)[0]

    assert client.download_text(reference) == "official pdf"
    assert session.gets[-1:] == [reference.source_url]


def test_client_retries_a_transient_list_request_once() -> None:
    session = OneFailureThenSuccessSession()
    client = CninfoFinancialAnnouncementClient(
        session=session,
        pdf_text=lambda content: content.decode("utf-8"),
    )

    references = client.list_financial_announcements("000568.SZ", AS_OF)

    assert len(references) == 1
    assert session.post_attempts == 5
