from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from .provider_source import ProviderBar


def _symbol(s: str) -> str:
    return s.split(".", 1)[0]


@dataclass
class AkShareDailyBarProvider:
    module: Any
    provider_name: str = "akshare"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        frame = self.module.stock_zh_a_hist(
            symbol=_symbol(security_id),
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
        return tuple(
            ProviderBar(
                security_id,
                date.fromisoformat(str(r["日期"])[:10]),
                Decimal(str(r["开盘"])),
                Decimal(str(r["最高"])),
                Decimal(str(r["最低"])),
                Decimal(str(r["收盘"])),
                int(r["成交量"]),
            )
            for _, r in frame.iterrows()
        )


@dataclass
class BaoStockDailyBarProvider:
    module: Any
    provider_name: str = "baostock"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        exchange, code = security_id.split(".", 1)
        self.module.login()
        try:
            result = self.module.query_history_k_data_plus(
                f"{exchange.lower()}.{code}",
                "date,open,high,low,close,volume",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            rows = []
            while result.error_code == "0" and result.next():
                rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        finally:
            self.module.logout()
        return tuple(
            ProviderBar(
                security_id,
                date.fromisoformat(r["date"]),
                Decimal(r["open"]),
                Decimal(r["high"]),
                Decimal(r["low"]),
                Decimal(r["close"]),
                int(r["volume"]),
            )
            for r in rows
            if r["close"]
        )


@dataclass
class FallbackDailyBarProvider:
    primary: Any
    fallback: Any
    provider_name: str = "akshare_with_baostock_fallback"

    def daily_bars(self, security_id: str, start: date, end: date) -> tuple[ProviderBar, ...]:
        return self.primary.daily_bars(security_id, start, end) or self.fallback.daily_bars(
            security_id, start, end
        )
