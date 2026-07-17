from datetime import date

import pytest

from backend.app.infrastructure.market.research_providers import BaoStockDailyBarProvider


class QueryResult:
    error_code = "0"
    fields = ["date", "open", "high", "low", "close", "volume"]

    def __init__(self) -> None:
        self._read = False

    def next(self) -> bool:
        if self._read:
            return False
        self._read = True
        return True

    def get_row_data(self) -> list[str]:
        return ["2026-07-17", "10", "11", "9", "10.5", "1200"]


class BaoStockModule:
    def __init__(self) -> None:
        self.queried_symbol: str | None = None
        self.logged_out = False

    def login(self) -> None:
        return None

    def logout(self) -> None:
        self.logged_out = True

    def query_history_k_data_plus(
        self,
        symbol: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> QueryResult:
        self.queried_symbol = symbol
        assert fields == "date,open,high,low,close,volume"
        assert (start_date, end_date) == ("2026-07-01", "2026-07-17")
        assert (frequency, adjustflag) == ("d", "3")
        return QueryResult()


@pytest.mark.parametrize(
    ("security_id", "provider_symbol"),
    [("600000.SH", "sh.600000"), ("000001.SZ", "sz.000001")],
)
def test_baostock_maps_canonical_security_id_to_provider_symbol(
    security_id: str,
    provider_symbol: str,
) -> None:
    module = BaoStockModule()
    provider = BaoStockDailyBarProvider(module)

    bars = provider.daily_bars(security_id, date(2026, 7, 1), date(2026, 7, 17))

    assert module.queried_symbol == provider_symbol
    assert module.logged_out is True
    assert bars[0].security_id == security_id
    assert bars[0].close.as_tuple().digits == (1, 0, 5)
