from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.infrastructure.market.akshare_research_provider import AkShareResearchProvider


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 22, 16, 0, tzinfo=SHANGHAI)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def iterrows(self) -> object:
        return iter(enumerate(self._rows))


class FakeAkShare:
    def stock_zh_a_hist(self, **kwargs: object) -> FakeFrame:
        assert kwargs == {
            "symbol": "000568",
            "period": "daily",
            "start_date": "20260701",
            "end_date": "20260722",
            "adjust": "",
        }
        return FakeFrame(
            [
                {
                    "日期": "2026-07-22",
                    "开盘": "85.00",
                    "最高": "87.00",
                    "最低": "84.00",
                    "收盘": "86.80",
                    "成交量": "12345",
                    "成交额": "1000000",
                }
            ]
        )

    def stock_financial_report_sina(self, **kwargs: object) -> FakeFrame:
        assert kwargs == {"stock": "sz000568", "symbol": "利润表"}
        return FakeFrame(
            [
                {
                    "报表日期": "2026-03-31",
                    "公告日期": "2026-04-29 18:00:00",
                    "营业总收入": "100.50",
                }
            ]
        )


def test_provider_returns_unadjusted_daily_bars_with_source_hash() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), lookback_days=21)

    bars = provider.daily_bars("000568.SZ", AS_OF)

    assert len(bars) == 1
    assert bars[0].security_id == "000568.SZ"
    assert bars[0].close == Decimal("86.80")
    assert bars[0].price_adjustment == "none"
    assert bars[0].available_at == datetime(2026, 7, 22, 15, 0, tzinfo=SHANGHAI)
    assert len(bars[0].source_hash) == 64


def test_provider_rejects_financial_rows_without_publication_time() -> None:
    class MissingPublicationAkShare(FakeAkShare):
        def stock_financial_report_sina(self, **kwargs: object) -> FakeFrame:
            del kwargs
            return FakeFrame([{"报表日期": "2026-03-31", "营业总收入": "100.50"}])

    provider = AkShareResearchProvider(MissingPublicationAkShare())

    assert provider.financials("000568.SZ", AS_OF) == ()
