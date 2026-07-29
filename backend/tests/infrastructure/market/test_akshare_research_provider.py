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

    def stock_zh_index_daily(self, **kwargs: object) -> FakeFrame:
        assert kwargs == {"symbol": "sh000001"}
        return FakeFrame(
            [
                {
                    "date": "2026-07-22",
                    "open": "3500",
                    "high": "3520",
                    "low": "3490",
                    "close": "3510",
                    "volume": "100",
                    "amount": "1000",
                }
            ]
        )

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
        assert kwargs["stock"] == "sz000568"
        assert kwargs["symbol"] in {"利润表", "资产负债表", "现金流量表"}
        fact_by_statement = {
            "利润表": "营业总收入",
            "资产负债表": "货币资金",
            "现金流量表": "经营活动产生的现金流量净额",
        }
        return FakeFrame(
            [
                {
                    "报告日": "20260331",
                    "公告日期": "2026-04-29",
                    fact_by_statement[str(kwargs["symbol"])]: "100.50",
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


def test_provider_uses_tencent_history_when_eastmoney_history_is_unavailable() -> None:
    class TencentFallbackAkShare(FakeAkShare):
        def stock_zh_a_hist(self, **kwargs: object) -> FakeFrame:
            del kwargs
            raise ConnectionError("eastmoney unavailable")

        def stock_zh_a_hist_tx(self, **kwargs: object) -> FakeFrame:
            assert kwargs["symbol"] == "sz000568"
            return FakeFrame(
                [{"date": "2026-07-22", "open": 85, "high": 87, "low": 84, "close": 86.8,
                  "amount": 12345}]
            )

    bars = AkShareResearchProvider(TencentFallbackAkShare(), lookback_days=21).daily_bars(
        "000568.SZ", AS_OF
    )

    assert bars[0].close == Decimal("86.8")


def test_provider_rejects_financial_rows_without_publication_time() -> None:
    class MissingPublicationAkShare(FakeAkShare):
        def stock_financial_report_sina(self, **kwargs: object) -> FakeFrame:
            del kwargs
            return FakeFrame([{"报告日": "20260331", "营业总收入": "100.50"}])

    provider = AkShareResearchProvider(MissingPublicationAkShare())

    assert provider.financials("000568.SZ", AS_OF) == ()


def test_provider_merges_sina_financial_statements_with_conservative_date_availability() -> None:
    provider = AkShareResearchProvider(FakeAkShare())

    financial = provider.financials("000568.SZ", AS_OF)

    assert len(financial) == 1
    assert financial[0].report_period == date(2026, 3, 31)
    assert financial[0].published_at == datetime(2026, 4, 29, 23, 59, 59, 999999, tzinfo=SHANGHAI)
    assert financial[0].facts == {
        "营业总收入": Decimal("100.50"),
        "货币资金": Decimal("100.50"),
        "经营活动产生的现金流量净额": Decimal("100.50"),
    }


def test_provider_hides_date_only_financial_disclosure_until_end_of_day() -> None:
    provider = AkShareResearchProvider(FakeAkShare())
    publication_day_midday = datetime(2026, 4, 29, 12, 0, tzinfo=SHANGHAI)

    assert provider.financials("000568.SZ", publication_day_midday) == ()


def test_provider_returns_current_quote_with_response_lineage() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    quotes = provider.quotes(("000568.SZ",), AS_OF)

    assert len(quotes) == 1
    assert quotes[0].price == Decimal("86.80")
    assert quotes[0].observed_at == AS_OF
    assert len(quotes[0].source_hash) == 64


def test_provider_hides_current_quote_when_retrieved_after_as_of_time() -> None:
    provider = AkShareResearchProvider(
        FakeAkShare(),
        now=lambda: AS_OF.replace(minute=AS_OF.minute + 1),
    )

    assert provider.quotes(("000568.SZ",), AS_OF) == ()


def test_provider_returns_calendar_with_retrieval_availability() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    calendar = provider.trade_calendar(date(2026, 7, 21), date(2026, 7, 22))

    assert [item.trade_date for item in calendar] == [date(2026, 7, 21), date(2026, 7, 22)]
    assert all(item.available_at == AS_OF and len(item.source_hash) == 64 for item in calendar)


def test_provider_hides_current_universe_when_retrieved_after_as_of_time() -> None:
    provider = AkShareResearchProvider(
        FakeAkShare(),
        now=lambda: AS_OF.replace(minute=AS_OF.minute + 1),
    )

    assert provider.universe(AS_OF) == ()


def test_provider_returns_scoped_security_master_without_loading_market_spot_pages() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    masters = provider.security_masters(("000568.SZ",), AS_OF)

    assert len(masters) == 1
    assert masters[0].security_id == "000568.SZ"
    assert masters[0].name == "泸州老窖"
    assert masters[0].listed_on == date(1994, 5, 9)
    assert masters[0].industry_id == "白酒"
    assert masters[0].is_suspended is False


def test_scoped_security_master_is_available_at_the_requested_analysis_time() -> None:
    provider = AkShareResearchProvider(
        FakeAkShare(), now=lambda: AS_OF.replace(minute=AS_OF.minute + 1)
    )

    masters = provider.security_masters(("000568.SZ",), AS_OF)

    assert masters[0].available_at == AS_OF


def test_provider_returns_unadjusted_index_bars_with_source_hash() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    bars = provider.index_daily_bars("000001.SH", AS_OF)

    assert len(bars) == 1
    assert bars[0].security_id == "000001.SH"
    assert bars[0].close == Decimal("3510")
    assert bars[0].available_at == datetime(2026, 7, 22, 15, 0, tzinfo=SHANGHAI)


def test_provider_normalizes_lowercase_exchange_suffix() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    assert provider.quotes(("000568.sz",), AS_OF)[0].security_id == "000568.SZ"


@pytest.mark.parametrize("security_id", ("510800.SH", "159566.SZ", "517110.SH"))
def test_provider_routes_etf_bars_and_quotes_to_etf_endpoints(security_id: str) -> None:
    code = security_id.partition(".")[0]

    class EtfAkShare(FakeAkShare):
        def stock_zh_a_hist(self, **kwargs: object) -> FakeFrame:
            raise AssertionError(f"stock endpoint must not receive ETF: {kwargs}")

        def fund_etf_hist_em(self, **kwargs: object) -> FakeFrame:
            assert kwargs["symbol"] == code
            assert kwargs["adjust"] == ""
            return FakeFrame(
                [
                    {
                        "日期": "2026-07-22",
                        "开盘": "1.40",
                        "最高": "1.44",
                        "最低": "1.39",
                        "收盘": "1.43",
                        "成交量": "12345",
                        "成交额": "1000000",
                    }
                ]
            )

        def stock_zh_a_spot_em(self) -> FakeFrame:
            raise AssertionError("stock spot endpoint must not receive ETF")

        def fund_etf_spot_em(self) -> FakeFrame:
            return FakeFrame([{"代码": code, "最新价": "1.43"}])

    provider = AkShareResearchProvider(EtfAkShare(), now=lambda: AS_OF)

    assert provider.daily_bars(security_id.lower(), AS_OF)[0].security_id == security_id
    assert provider.quotes((security_id,), AS_OF)[0].price == Decimal("1.43")


def test_provider_excludes_universe_security_with_nonzero_price_but_no_status() -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    assert provider.universe(AS_OF) == ()


@pytest.mark.parametrize("security_id", ("000568", "000568.XX", "ABC.SZ"))
def test_provider_rejects_noncanonical_security_suffixes(security_id: str) -> None:
    provider = AkShareResearchProvider(FakeAkShare(), now=lambda: AS_OF)

    with pytest.raises(ValueError, match="security id"):
        provider.daily_bars(security_id, AS_OF)
