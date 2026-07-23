#!/usr/bin/env python3
"""Refresh the local market fixture used by the browser-test composition.

The application only reads the DA-owned fixture.  This script is the explicit
boundary where a user's local cache (or Eastmoney when enabled) is copied into
that fixture, so every stack start replaces the previous snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


SECURITIES = ("000425.SZ", "000568.SZ", "159566.SZ", "517110.SH", "601899.SH")
DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "LA" / "data" / "cache" / "daily_bars"
DEFAULT_DEST = Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "local_market"
SEED_SOURCE = DEFAULT_DEST / "seed"


def _eastmoney(symbol: str) -> dict[str, Any]:
    market = "1" if symbol.endswith(".SH") else "0"
    code = symbol.split(".")[0]
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={market}.{code}&klt=101&fqt=1&beg=20200101&end=20991231"
        "&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57"
    )
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    payload = response.json()
    rows = (payload.get("data") or {}).get("klines") or []
    if not rows:
        raise RuntimeError(f"no market rows returned for {symbol}")
    bars = []
    for row in rows:
        date, open_, close, high, low, volume, amount = row.split(",")
        bars.append(
            {
                "trade_date": date.replace("-", ""),
                "open": float(open_),
                "close": float(close),
                "high": float(high),
                "low": float(low),
                "volume": float(volume),
                "amount": float(amount),
                "source": "eastmoney_direct_qfq",
            }
        )
    return {"symbol": symbol, "price_adjust": "qfq", "bars": bars}


def _from_cache(path: Path, symbol: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bars = []
    for item in payload.get("bars", []):
        fields = item.get("fields", {})
        bars.append(
            {
                "trade_date": str(item["trade_time"])[:10].replace("-", ""),
                "open": float(fields["open"]),
                "close": float(fields["close"]),
                "high": float(fields["high"]),
                "low": float(fields["low"]),
                "volume": float(fields.get("volume", fields.get("vol", 0))),
                "amount": float(fields.get("amount", 0)),
                "source": fields.get("price_source", "local_cache"),
            }
        )
    if not bars:
        raise RuntimeError(f"no market rows in {path}")
    return {"symbol": symbol, "price_adjust": payload.get("price_adjust", "qfq"), "bars": bars}


def refresh(source: Path, destination: Path) -> Path:
    records: dict[str, dict[str, Any]] = {}
    for symbol in SECURITIES:
        source_file = source / f"{symbol}.json"
        if source_file.exists():
            records[symbol] = _from_cache(source_file, symbol)
        elif (SEED_SOURCE / f"{symbol}.json").exists():
            records[symbol] = _from_cache(SEED_SOURCE / f"{symbol}.json", symbol)
        else:
            records[symbol] = _eastmoney(symbol)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "refreshed_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "symbols": SECURITIES,
        "records": {
            symbol: hashlib.sha256(
                json.dumps(records[symbol], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            for symbol in SECURITIES
        },
    }
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        temp_path = Path(temp)
        (temp_path / "daily_bars.json").write_text(
            json.dumps(records, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        (temp_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temp_path / "daily_bars.json", destination / "daily_bars.json")
        os.replace(temp_path / "manifest.json", destination / "manifest.json")
    return destination / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(os.getenv("DA_MARKET_SOURCE", DEFAULT_SOURCE)))
    parser.add_argument("--destination", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    print(refresh(args.source, args.destination))


if __name__ == "__main__":
    main()
