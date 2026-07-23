from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from backend.app.infrastructure.market.akshare_research_provider import AkShareResearchProvider


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 7, 22, 16, 0, tzinfo=SHANGHAI)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def iterrows(self) -> object:
        return iter(enumerate(self._rows))


class FakeAkShare:
    def tool_trade_date_hist_sina(self) -> FakeFrame:
        return FakeFrame([{"trade_date": "2026-07-21"}, {"trade_date": "2026-07-22"}])

    def stock_info_a_code_name(self) -> FakeFrame:
        return FakeFrame([{"code": "000568", "name": "泸州老窖"}])

    def stock_individual_info_em(self, **kwargs: object) -> FakeFrame:
        assert kwargs == {"symbol": "000568"}
        return FakeFrame(
            [{"item": "上市时间", "value": "19940509"}, {"item": "行业", "value": "白酒"}]
        )

    def stock_zh_a_spot_em(self) -> FakeFrame:
        return FakeFrame([{"代码": "000568", "最新价": "86.80"}])

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


def test_provider_returns_current_quote_with_response_lineage() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    quotes = provider.quotes(("000568.SZ",), AS_OF)

    assert len(quotes) == 1
    assert quotes[0].price == Decimal("86.80")
    assert quotes[0].observed_at == AS_OF
    assert len(quotes[0].source_hash) == 64


def test_provider_returns_calendar_and_universe_with_retrieval_availability() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    calendar = provider.trade_calendar(date(2026, 7, 21), date(2026, 7, 22))
    universe = provider.universe(AS_OF)

    assert [item.trade_date for item in calendar] == [date(2026, 7, 21), date(2026, 7, 22)]
    assert all(item.available_at == AS_OF and len(item.source_hash) == 64 for item in calendar)
    assert universe[0].security_id == "000568.SZ"
    assert universe[0].listed_on == date(1994, 5, 9)
    assert universe[0].industry_id == "白酒"
    assert universe[0].available_at == AS_OF


@pytest.mark.parametrize("security_id", ("000568", "000568.XX", "ABC.SZ"))
def test_provider_rejects_noncanonical_security_suffixes(security_id: str) -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    with pytest.raises(ValueError, match="security id"):
        provider.daily_bars(security_id, AS_OF)
