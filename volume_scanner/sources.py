"""Alternative market-data backends.

Currently: Alpaca (https://alpaca.markets) via its REST market-data API.
Only the `requests` library is needed — no Alpaca SDK.

Credentials are resolved in this order:
  1. Explicit key/secret passed in (CLI --alpaca-key / --alpaca-secret)
  2. Environment vars APCA_API_KEY_ID / APCA_API_SECRET_KEY
  3. A JSON file at volume_scanner/data/alpaca_keys.json  {"key": "...", "secret": "..."}

Free Alpaca plans use the IEX feed (a subset of total US volume). Relative
volume (today vs. baseline) is still meaningful; absolute volume is understated.
US stocks only — international symbols should fall back to yfinance.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
KEYS_FILE = os.path.join(os.path.dirname(__file__), "data", "alpaca_keys.json")

_TIMEFRAME = {
    "1d": "1Day", "1m": "1Min", "2m": "2Min", "5m": "5Min",
    "15m": "15Min", "30m": "30Min", "60m": "1Hour", "1h": "1Hour",
}


class AlpacaAuthError(RuntimeError):
    pass


def resolve_credentials(key: str | None = None, secret: str | None = None) -> tuple[str, str]:
    key = key or os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = secret or os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret) and os.path.exists(KEYS_FILE):
        try:
            d = json.load(open(KEYS_FILE))
            key = key or d.get("key")
            secret = secret or d.get("secret")
        except Exception:
            pass
    if not (key and secret):
        raise AlpacaAuthError(
            "No Alpaca API credentials found. Provide --alpaca-key/--alpaca-secret, "
            "set APCA_API_KEY_ID / APCA_API_SECRET_KEY, or run with --save-keys once."
        )
    return key, secret


def save_credentials(key: str, secret: str) -> str:
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump({"key": key, "secret": secret}, f)
    return KEYS_FILE


def fetch_valid_symbols(key: str, secret: str) -> set[str]:
    """Return the set of tradable US-equity symbols Alpaca actually knows.

    Used to pre-filter our (Yahoo-style) universe so we never send a symbol
    Alpaca rejects — a single bad symbol 400s an entire multi-symbol request.
    Symbols come back in Alpaca format (e.g. 'BRK.B', not Yahoo's 'BRK-B').
    """
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    r = requests.get(
        ALPACA_ASSETS_URL, headers=headers,
        params={"status": "active", "asset_class": "us_equity"}, timeout=60,
    )
    if r.status_code in (401, 403):
        raise AlpacaAuthError(
            f"Alpaca rejected the credentials (HTTP {r.status_code}) on the assets "
            "endpoint. Check your key/secret are valid."
        )
    if r.status_code != 200:
        raise RuntimeError(f"Alpaca assets error {r.status_code}: {r.text[:200]}")
    return {a["symbol"] for a in r.json() if a.get("tradable")}


def _period_to_days(period: str, default: int = 95) -> int:
    p = (period or "").strip().lower()
    try:
        if p.endswith("mo"):
            return int(p[:-2]) * 31
        if p.endswith("y"):
            return int(p[:-1]) * 366
        if p.endswith("d"):
            return int(p[:-1])
        return int(p)
    except Exception:
        return default


def fetch_bars(
    symbols: list[str],
    interval: str,
    *,
    key: str,
    secret: str,
    lookback_days: int = 20,
    period: str = "3mo",
    intraday_period: str = "10d",
    feed: str = "iex",
    req_batch: int = 200,
) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLCV DataFrame} with a tz-aware DatetimeIndex."""
    timeframe = _TIMEFRAME.get(interval, "1Day")
    now = datetime.now(timezone.utc)
    if timeframe == "1Day":
        days_back = max(_period_to_days(period, 95), lookback_days * 2 + 15)
    else:
        days_back = max(_period_to_days(intraday_period, 10), 7)
    start = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    collected: dict[str, list] = {}

    for i in range(0, len(symbols), req_batch):
        batch = list(symbols[i : i + req_batch])
        page_token = None
        while True:
            if not batch:
                break
            params = {
                "symbols": ",".join(batch),
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "limit": 10000,
                "feed": feed,
                "adjustment": "raw",
            }
            if page_token:
                params["page_token"] = page_token

            # Free tier is 200 req/min. On a 429, respect Retry-After and retry the
            # SAME request a few times rather than failing the whole chunk (which
            # would cascade into the scanner's slow whole-chunk retry rounds).
            for attempt in range(6):
                r = requests.get(ALPACA_BARS_URL, headers=headers, params=params, timeout=30)
                if r.status_code != 429:
                    break
                try:
                    wait = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    wait = 0.0
                wait = wait or min(2 ** attempt, 30)
                time.sleep(wait)
            else:
                raise RuntimeError("Alpaca rate limit (429) persisted after retries.")

            if r.status_code in (401, 403):
                raise AlpacaAuthError(
                    f"Alpaca rejected the credentials (HTTP {r.status_code}). "
                    "Check your key/secret are valid market-data keys."
                )
            if r.status_code == 400:
                # One bad symbol 400s the whole request; drop it and retry the
                # batch rather than losing every symbol in it.
                msg = ""
                try:
                    msg = r.json().get("message", "")
                except Exception:
                    pass
                bad = msg.split("invalid symbol:", 1)[1].strip() if "invalid symbol:" in msg else None
                if bad and bad in batch:
                    batch.remove(bad)
                    page_token = None
                    continue
                raise RuntimeError(f"Alpaca error 400: {r.text[:200]}")
            if r.status_code != 200:
                raise RuntimeError(f"Alpaca error {r.status_code}: {r.text[:200]}")
            data = r.json()
            for sym, blist in (data.get("bars") or {}).items():
                collected.setdefault(sym, []).extend(blist)
            page_token = data.get("next_page_token")
            if not page_token:
                break

    frames: dict[str, pd.DataFrame] = {}
    for sym, blist in collected.items():
        if not blist:
            continue
        df = pd.DataFrame(blist)
        df["t"] = pd.to_datetime(df["t"], utc=True)
        df = df.set_index("t").rename(
            columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}
        )
        frames[sym] = df[["Open", "High", "Low", "Close", "Volume"]]
    return frames
