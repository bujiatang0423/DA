from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from threading import Event
from zoneinfo import ZoneInfo
import requests

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.persistence.portfolio_rows import (
    PortfolioLotProjectionRow,
    PortfolioPositionQuoteRow,
    PortfolioSnapshotProjectionRow,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def realtime_prices(symbols: tuple[str, ...]) -> dict[str, tuple[Decimal, str]]:
    """Return the external provider's current or most recent close prices."""
    try:
        codes = ",".join(
            "s_" + ("sh" if symbol.endswith(".SH") else "sz") + symbol[:6]
            for symbol in symbols
        )
        response = requests.get(
            "https://hq.sinajs.cn/list=" + codes,
            timeout=8,
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        result: dict[str, tuple[Decimal, str]] = {}
        for line in response.text.splitlines():
            if '="' not in line:
                continue
            symbol = line.split("hq_str_s_", 1)[-1].split('="', 1)[0]
            fields = line.split('="', 1)[1].rstrip('";').split(",")
            if len(fields) > 1 and fields[1]:
                suffix = ".SH" if symbol.startswith("sh") else ".SZ"
                price = Decimal(fields[1])
                if price > 0:
                    result[symbol[2:] + suffix] = (price, "sina_quote")
        return result
    except Exception:
        return {}


def refresh_portfolio_quotes(sessions: sessionmaker) -> None:
    """Refresh quotes exclusively from external providers or stored real quotes."""
    now = datetime.now(SHANGHAI)
    with sessions.begin() as session:
        portfolios = session.scalars(select(PortfolioSnapshotProjectionRow)).all()
        for projection in portfolios:
            lots = session.scalars(
                select(PortfolioLotProjectionRow).where(
                    PortfolioLotProjectionRow.portfolio_id == projection.portfolio_id
                )
            ).all()
            total = Decimal(str(projection.cash))
            prices = realtime_prices(tuple(lot.security_id for lot in lots))
            stored_prices = _latest_external_prices(session, projection.portfolio_id)
            missing_price = False
            for lot in lots:
                quote = prices.get(lot.security_id)
                has_external_quote = quote is not None and quote[0] > 0
                if not has_external_quote:
                    quote = None
                if quote is None:
                    quote = stored_prices.get(lot.security_id)
                if quote is None:
                    missing_price = True
                    continue
                price, source = quote
                if has_external_quote:
                    session.add(PortfolioPositionQuoteRow(
                        portfolio_id=projection.portfolio_id,
                        security_id=lot.security_id,
                        observed_at=now,
                        price=price,
                        source=source,
                    ))
                total += price * int(lot.quantity)
            if not missing_price:
                projection.equity = total


def _latest_external_prices(
    session: Session,
    portfolio_id: str,
) -> dict[str, tuple[Decimal, str]]:
    rows = session.scalars(
        select(PortfolioPositionQuoteRow)
        .where(PortfolioPositionQuoteRow.portfolio_id == portfolio_id)
        .order_by(
            PortfolioPositionQuoteRow.security_id,
            PortfolioPositionQuoteRow.observed_at.desc(),
        )
    ).all()
    prices: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        if _is_external_source(row.source):
            prices.setdefault(row.security_id, (Decimal(str(row.price)), row.source))
    return prices


def _is_external_source(source: str) -> bool:
    return source.startswith(("akshare_", "sina_", "eastmoney_"))


def run_quote_scheduler(sessions: sessionmaker, stop: Event) -> None:
    try:
        refresh_portfolio_quotes(sessions)
    except Exception:
        pass
    while not stop.wait(600):
        try:
            refresh_portfolio_quotes(sessions)
        except Exception:
            continue
