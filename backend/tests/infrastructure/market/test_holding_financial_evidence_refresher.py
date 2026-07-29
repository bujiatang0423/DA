from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.app.infrastructure.market.holding_financial_evidence import (
    FinancialEvidenceRefreshError,
    FinancialAnnouncementReference,
    HoldingFinancialEvidenceRefresher,
)
from backend.app.infrastructure.market.official_evidence import OfficialEvidenceStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 23, 16, 0, tzinfo=SHANGHAI)


@dataclass
class FakeAnnouncementClient:
    references: tuple[FinancialAnnouncementReference, ...]
    texts: dict[str, str]

    def __post_init__(self) -> None:
        self.listed: list[str] = []
        self.downloaded: list[str] = []

    def list_financial_announcements(
        self,
        *,
        security_id: str,
        as_of_time: datetime,
    ) -> tuple[FinancialAnnouncementReference, ...]:
        del as_of_time
        self.listed.append(security_id)
        return tuple(item for item in self.references if item.security_id == security_id)

    def download_text(self, reference: FinancialAnnouncementReference) -> str:
        self.downloaded.append(reference.source_url)
        return self.texts[reference.source_url]


def _reference(**overrides: object) -> FinancialAnnouncementReference:
    values: dict[str, object] = {
        "security_id": "000568.SZ",
        "report_period": date(2026, 3, 31),
        "issuer": "泸州老窖股份有限公司",
        "title": "2026 年第一季度报告",
        "published_at": datetime(2026, 4, 28, 18, 0, tzinfo=SHANGHAI),
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-28/123.pdf",
    }
    values.update(overrides)
    return FinancialAnnouncementReference(**values)


def test_refresh_downloads_missing_stock_announcement_and_persists_official_document() -> None:
    reference = _reference()
    client = FakeAnnouncementClient((reference,), {reference.source_url: "官方财报正文"})
    store = OfficialEvidenceStore.in_memory()
    refresher = HoldingFinancialEvidenceRefresher(store, client, now=lambda: AS_OF)

    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    documents = store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",))
    assert client.listed == ["000568.SZ"]
    assert client.downloaded == [reference.source_url]
    assert len(documents) == 1
    assert documents[0].report_period == date(2026, 3, 31)
    assert documents[0].text == "官方财报正文"


def test_refreshed_document_preserves_its_actual_observation_time() -> None:
    reference = _reference()
    client = FakeAnnouncementClient((reference,), {reference.source_url: "官方财报正文"})
    store = OfficialEvidenceStore.in_memory()
    refresher = HoldingFinancialEvidenceRefresher(
        store,
        client,
        now=lambda: AS_OF.replace(hour=17),
    )

    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",)) == ()
    assert store.documents(
        as_of_time=AS_OF.replace(hour=17), security_ids=("000568.SZ",)
    )


def test_refresh_does_not_download_an_already_persisted_report_period() -> None:
    reference = _reference()
    client = FakeAnnouncementClient((reference,), {reference.source_url: "官方财报正文"})
    store = OfficialEvidenceStore.in_memory()
    refresher = HoldingFinancialEvidenceRefresher(store, client, now=lambda: AS_OF)
    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)
    client.downloaded.clear()

    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert client.downloaded == []


def test_refresh_downloads_only_the_latest_report_period_for_each_stock() -> None:
    newest = _reference()
    older = _reference(
        report_period=date(2025, 12, 31),
        title="2025 年年度报告",
        source_url="https://static.cninfo.com.cn/finalpage/2026-03-30/older.pdf",
    )
    client = FakeAnnouncementClient(
        (newest, older),
        {newest.source_url: "最新财报正文", older.source_url: "旧财报正文"},
    )
    store = OfficialEvidenceStore.in_memory()
    refresher = HoldingFinancialEvidenceRefresher(store, client, now=lambda: AS_OF)

    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert client.downloaded == [newest.source_url]


def test_refresh_selects_one_most_recent_announcement_for_the_latest_period() -> None:
    earlier = _reference(source_url="https://static.cninfo.com.cn/finalpage/2026-04-28/old.pdf")
    later = _reference(
        source_url="https://static.cninfo.com.cn/finalpage/2026-04-29/new.pdf",
        published_at=datetime(2026, 4, 29, 18, 0, tzinfo=SHANGHAI),
    )
    client = FakeAnnouncementClient(
        (earlier, later),
        {earlier.source_url: "旧版本", later.source_url: "新版本"},
    )
    refresher = HoldingFinancialEvidenceRefresher(
        OfficialEvidenceStore.in_memory(),
        client,
        now=lambda: AS_OF,
    )

    refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert client.downloaded == [later.source_url]


def test_refresh_skips_etfs_and_fails_closed_when_no_visible_announcement_exists() -> None:
    reference = _reference(published_at=AS_OF.replace(day=24))
    client = FakeAnnouncementClient((reference,), {reference.source_url: "未来公告"})
    store = OfficialEvidenceStore.in_memory()
    refresher = HoldingFinancialEvidenceRefresher(store, client, now=lambda: AS_OF)

    with pytest.raises(FinancialEvidenceRefreshError, match="no visible official financial"):
        refresher.refresh(security_ids=("159566.SZ", "000568.SZ"), as_of_time=AS_OF)

    assert client.listed == ["000568.SZ"]
    assert client.downloaded == []
    assert store.documents(as_of_time=AS_OF, security_ids=("000568.SZ",)) == ()


def test_refresh_wraps_source_failures_with_the_holding_market_data_code() -> None:
    class FailingClient(FakeAnnouncementClient):
        def list_financial_announcements(
            self,
            *,
            security_id: str,
            as_of_time: datetime,
        ) -> tuple[FinancialAnnouncementReference, ...]:
            del security_id, as_of_time
            raise TimeoutError("source timeout")

    client = FailingClient((), {})
    refresher = HoldingFinancialEvidenceRefresher(
        OfficialEvidenceStore.in_memory(),
        client,
        now=lambda: AS_OF,
    )

    with pytest.raises(FinancialEvidenceRefreshError) as error:
        refresher.refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert error.value.code == "HOLDING_MARKET_DATA_MISSING"


def test_refresh_uses_existing_official_report_when_lookup_is_temporarily_unavailable() -> None:
    reference = _reference()
    store = OfficialEvidenceStore.in_memory()
    HoldingFinancialEvidenceRefresher(
        store,
        FakeAnnouncementClient((reference,), {reference.source_url: "官方财报正文"}),
        now=lambda: AS_OF,
    ).refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    class FailingClient(FakeAnnouncementClient):
        def list_financial_announcements(
            self,
            *,
            security_id: str,
            as_of_time: datetime,
        ) -> tuple[FinancialAnnouncementReference, ...]:
            del security_id, as_of_time
            raise TimeoutError("source timeout")

    result = HoldingFinancialEvidenceRefresher(
        store,
        FailingClient((), {}),
        now=lambda: AS_OF,
    ).refresh(security_ids=("000568.SZ",), as_of_time=AS_OF)

    assert result.available_at is None


def test_refresh_error_uses_holding_market_data_failure_code() -> None:
    assert FinancialEvidenceRefreshError.code == "HOLDING_MARKET_DATA_MISSING"
