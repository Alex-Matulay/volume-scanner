"""Core end-of-day volume scanner.

For each ticker it compares the most recent day's volume against a trailing
baseline and surfaces unusual activity via several metrics:

  rvol        last day's volume / average of the prior N days
  vol_zscore  how many std devs the last volume is above the baseline mean
  pct_change  last close % change vs. previous close
  dollar_vol  last volume * last close (a liquidity filter)

A high rvol with a price move is the classic "something is happening" signal.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace

import pandas as pd
import yfinance as yf

from . import sources


@dataclass
class ScanConfig:
    lookback_days: int = 20      # trailing baseline length
    period: str = "3mo"          # how much history to pull
    chunk_size: int = 200        # tickers per yfinance batch
    min_dollar_vol: float = 1_000_000.0   # drop illiquid names
    min_avg_vol: float = 50_000.0
    min_rvol: float = 2.0        # only keep clear spikes
    # Intraday mode (free, ~15 min delayed via yfinance)
    intraday_interval: str = "5m"   # bar size: 1m, 2m, 5m, 15m, 30m, 60m
    intraday_period: str = "10d"    # history window (5m bars: max ~60d)
    # Pacing / rate-limit handling (Yahoo free endpoint throttles bulk scans)
    pause_between_chunks: float = 1.0   # seconds to wait between batches
    max_retry_rounds: int = 4           # extra passes over rate-limited tickers
    retry_backoff: float = 30.0         # base seconds to wait before a retry round
    threads: bool = True                # parallel download within a batch
    # Data source: "yfinance" (default, US+UK+EU) or "alpaca" (fast, US only)
    source: str = "yfinance"
    alpaca_key: str | None = None
    alpaca_secret: str | None = None
    alpaca_feed: str = "iex"            # free plans use IEX
    # Alpaca's free IEX feed only sees a fraction of total volume, so absolute
    # numbers are understated. When True, the fast Alpaca pass is used only to
    # *screen* candidates, then their real consolidated volume is pulled from
    # yfinance so the reported figures match TradingView / brokers.
    enrich: bool = True


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _extract(data: pd.DataFrame, ticker: str, single: bool) -> pd.DataFrame | None:
    if data is None or data.empty:
        return None
    # Modern yfinance returns MultiIndex columns with the ticker on a level,
    # even for a single symbol. Select that ticker's sub-frame when present.
    if isinstance(data.columns, pd.MultiIndex):
        for level in range(data.columns.nlevels):
            if ticker in data.columns.get_level_values(level):
                return data.xs(ticker, axis=1, level=level)
        return data if single else None
    return data


def _metrics_for(df: pd.DataFrame, ticker: str, cfg: ScanConfig) -> dict | None:
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Volume", "Close"])
    if len(df) < cfg.lookback_days + 2:
        return None

    vol = df["Volume"].astype(float)
    close = df["Close"].astype(float)
    open_ = df["Open"].astype(float) if "Open" in df.columns else close
    high = df["High"].astype(float) if "High" in df.columns else pd.concat([open_, close], axis=1).max(axis=1)
    low = df["Low"].astype(float) if "Low" in df.columns else pd.concat([open_, close], axis=1).min(axis=1)

    last_vol = float(vol.iloc[-1])
    prev_vol = float(vol.iloc[-2])
    baseline = vol.iloc[-(cfg.lookback_days + 1) : -1]
    avg = float(baseline.mean())
    std = float(baseline.std())
    # Dedicated trailing 10-session average (excludes the most recent day).
    base10 = vol.iloc[-(10 + 1) : -1]
    avg10 = float(base10.mean()) if len(base10) else avg
    if avg <= 0 or last_vol <= 0:
        return None

    last_open = float(open_.iloc[-1])
    last_close = float(close.iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])
    prev_close = float(close.iloc[-2])
    pct_change = (last_close / prev_close - 1.0) * 100.0 if prev_close else float("nan")
    dollar_vol = last_vol * last_close

    rvol = last_vol / avg
    zscore = (last_vol - avg) / std if std > 0 else float("nan")

    # --- Intraday volatility (the day's high-low swing) ---------------------
    day_range = last_high - last_low
    day_range_pct = day_range / last_close * 100.0 if last_close else float("nan")
    # How volatile vs. its own normal: today's range / average daily range.
    day_ranges = (high - low).iloc[-(cfg.lookback_days + 1) : -1]
    avg_range = float(day_ranges.mean()) if len(day_ranges) else float("nan")
    range_vs_avg = day_range / avg_range if avg_range and avg_range > 0 else float("nan")

    # --- Up vs. down volume (bought up vs. sold off) -----------------------
    # With a daily bar we can't see each trade, so infer pressure from where the
    # close landed in the day's range (Close Location Value, -1..+1): closing
    # near the high = buyers won; near the low = sellers won. Map to an estimated
    # buy-volume share so it reads like "~70% buying".
    if day_range > 0:
        clv = ((last_close - last_low) - (last_high - last_close)) / day_range
    else:
        clv = 0.0
    buy_vol_pct = (clv + 1.0) / 2.0 * 100.0
    flow = "bought up" if clv >= 0.3 else ("sold off" if clv <= -0.3 else "mixed")

    return {
        "symbol": ticker,
        "date": df.index[-1].date().isoformat(),
        "avg_volume": int(avg),
        "last_volume": int(last_vol),
        "prev_volume": int(prev_vol),
        "avg_volume_10d": int(avg10),
        "rvol": round(rvol, 2),
        "open": round(last_open, 4),
        "close": round(last_close, 4),
        "pct_change": round(pct_change, 2),
        "day_range_pct": round(day_range_pct, 2) if not math.isnan(day_range_pct) else None,
        "range_vs_avg": round(range_vs_avg, 2) if not math.isnan(range_vs_avg) else None,
        "buy_vol_pct": round(buy_vol_pct, 1),
        "flow": flow,
        "vol_zscore": round(zscore, 2) if not math.isnan(zscore) else None,
        "dollar_vol": int(dollar_vol),
        "direction": "up" if pct_change > 0 else ("down" if pct_change < 0 else "flat"),
        "notes": "",
    }


_RESULT_COLS = [
    "symbol", "date", "avg_volume", "last_volume", "prev_volume",
    "avg_volume_10d", "rvol", "open", "close", "pct_change",
    "day_range_pct", "range_vs_avg", "buy_vol_pct", "flow",
    "vol_zscore", "dollar_vol", "direction", "notes",
]


def _yf_download(chunk: list[str], cfg: ScanConfig, intraday: bool):
    if intraday:
        return yf.download(
            chunk, period=cfg.intraday_period, interval=cfg.intraday_interval,
            group_by="ticker", auto_adjust=False, threads=cfg.threads,
            progress=False, prepost=False,
        )
    return yf.download(
        chunk, period=cfg.period, interval="1d", group_by="ticker",
        auto_adjust=False, threads=cfg.threads, progress=False,
    )


def _fetch_chunk(chunk: list[str], cfg: ScanConfig, intraday: bool) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLCV DataFrame} for one batch, from the configured source."""
    if cfg.source == "alpaca":
        key, secret = sources.resolve_credentials(cfg.alpaca_key, cfg.alpaca_secret)
        interval = cfg.intraday_interval if intraday else "1d"
        return sources.fetch_bars(
            chunk, interval, key=key, secret=secret,
            lookback_days=cfg.lookback_days, period=cfg.period,
            intraday_period=cfg.intraday_period, feed=cfg.alpaca_feed,
        )
    data = _yf_download(chunk, cfg, intraday)
    single = len(chunk) == 1
    if data is None or getattr(data, "empty", True):
        return {}
    out: dict[str, pd.DataFrame] = {}
    for t in chunk:
        df = _extract(data, t, single)
        if df is not None and not getattr(df, "empty", True):
            out[t] = df
    return out


def _scan_engine(tickers, cfg, intraday, progress) -> pd.DataFrame:
    """Shared scan loop with pacing + retry of rate-limited tickers."""
    cfg = cfg or ScanConfig()
    metrics_fn = _intraday_metrics if intraday else _metrics_for
    rows: list[dict] = []
    total = len(tickers)
    done = 0
    remaining = list(tickers)
    # yfinance returns throttled symbols as empty within a *successful* batch, so a
    # missing symbol there is worth retrying. Alpaca returns HTTP 200 and simply
    # omits symbols it has no data for — retrying those is pointless.
    retry_missing = cfg.source != "alpaca"

    for rnd in range(cfg.max_retry_rounds + 1):
        failed: list[str] = []  # whole-chunk fetch errors (transient -> retry)
        for chunk in _chunks(remaining, cfg.chunk_size):
            try:
                frames = _fetch_chunk(chunk, cfg, intraday)
            except sources.AlpacaAuthError:
                raise  # credential problems should surface immediately
            except Exception:
                failed.extend(chunk)  # request raised (network / 429) -> retry
                done += len(chunk)
                if progress:
                    progress(done, total)
                continue

            for t in chunk:
                df = frames.get(t)
                if df is None or getattr(df, "empty", True):
                    if retry_missing:
                        failed.append(t)  # likely throttled -> retry later
                    # else (Alpaca): no data for this symbol, skip permanently
                    continue
                m = metrics_fn(df, t, cfg)
                if m:
                    rows.append(m)
            # only count first-round tickers toward the headline progress
            if rnd == 0:
                done += len(chunk)
                if progress:
                    progress(done, total)
            if cfg.pause_between_chunks:
                time.sleep(cfg.pause_between_chunks)

        if not failed or rnd == cfg.max_retry_rounds:
            break
        wait = cfg.retry_backoff * (rnd + 1)
        print(f"\n  {len(failed):,} tickers returned no data — waiting {wait:.0f}s "
              f"then retry round {rnd + 1}/{cfg.max_retry_rounds}...", flush=True)
        time.sleep(wait)
        remaining = failed

    if not rows:
        return pd.DataFrame(columns=_RESULT_COLS)

    df = pd.DataFrame(rows).drop_duplicates(subset="symbol")
    df = df[
        (df["rvol"] >= cfg.min_rvol)
        & (df["dollar_vol"] >= cfg.min_dollar_vol)
        & (df["avg_volume"] >= cfg.min_avg_vol)
    ]
    return df.sort_values("rvol", ascending=False).reset_index(drop=True)


def _run(tickers, cfg, intraday, progress) -> pd.DataFrame:
    """Dispatch a scan, splitting US (Alpaca) from international (yfinance)."""
    cfg = cfg or ScanConfig()
    if cfg.source != "alpaca":
        out = _scan_engine(tickers, cfg, intraday, progress)
        if not out.empty:
            out["notes"] = "yfinance (consolidated)"
        return out

    # Alpaca covers US only; route '.'-suffixed symbols (e.g. .L/.DE) to yfinance.
    us = [t for t in tickers if "." not in t]
    intl = [t for t in tickers if "." in t]
    parts: list[pd.DataFrame] = []
    if us:
        # Pre-filter against Alpaca's authoritative tradable list. Alpaca uses '.'
        # for share classes (BRK.B) where Yahoo uses '-' (BRK-B); preferred/unknown
        # tickers (e.g. ABR-D) simply aren't there. Sending one Alpaca doesn't know
        # 400s the entire batch, so we drop those up front and map names back after.
        key, secret = sources.resolve_credentials(cfg.alpaca_key, cfg.alpaca_secret)
        valid = sources.fetch_valid_symbols(key, secret)
        alpaca_syms = [t.replace("-", ".") for t in us if t.replace("-", ".") in valid]
        back = {t.replace("-", "."): t for t in us}  # alpaca form -> original
        dropped = len(us) - len(alpaca_syms)
        if progress and dropped:
            print(f"\n  {dropped:,} symbols not on Alpaca (preferred/unlisted) "
                  f"skipped; scanning {len(alpaca_syms):,} on Alpaca...", flush=True)
        acfg = replace(cfg, chunk_size=max(cfg.chunk_size, 200), pause_between_chunks=0.0)

        if cfg.enrich:
            # IEX volume is a fraction of true volume, so absolute filters
            # (dollar/avg volume) would wrongly drop liquid names — screen on the
            # RVOL *ratio* only (relaxed a touch to catch IEX understatement),
            # then re-measure the survivors on accurate consolidated volume.
            screen_rvol = max(2.0, cfg.min_rvol * 0.7)
            scfg = replace(acfg, min_rvol=screen_rvol, min_dollar_vol=0.0, min_avg_vol=0.0)
            cand = _scan_engine(alpaca_syms, scfg, intraday, progress)
            if not cand.empty:
                cand = cand.sort_values("rvol", ascending=False).head(500)
                cand_syms = [back.get(s, s) for s in cand["symbol"]]
                if progress:
                    print(f"\n  Re-measuring {len(cand_syms):,} candidates on accurate "
                          f"consolidated volume (yfinance)...", flush=True)
                ycfg = replace(cfg, source="yfinance")
                us_part = _scan_engine(cand_syms, ycfg, intraday, None)
                if not us_part.empty:
                    us_part["notes"] = "yfinance (consolidated)"
                else:
                    # Enrichment produced nothing (e.g. Yahoo throttled a CI run).
                    # Fall back to the IEX screen so results aren't lost; apply the
                    # real RVOL on the (still-valid) ratio and flag the caveat.
                    cand = cand[cand["rvol"] >= cfg.min_rvol].copy()
                    cand["symbol"] = cand["symbol"].map(lambda s: back.get(s, s))
                    cand["notes"] = "Alpaca IEX (partial volume — enrichment unavailable)"
                    us_part = cand
            else:
                us_part = pd.DataFrame(columns=_RESULT_COLS)
        else:
            us_part = _scan_engine(alpaca_syms, acfg, intraday, progress)
            if not us_part.empty:
                us_part["symbol"] = us_part["symbol"].map(lambda s: back.get(s, s))
                us_part["notes"] = "Alpaca IEX (partial volume)"
        parts.append(us_part)
    if intl:
        if progress:
            print(f"\n  {len(intl):,} non-US symbols -> yfinance fallback...", flush=True)
        ycfg = replace(cfg, source="yfinance")
        intl_part = _scan_engine(intl, ycfg, intraday, None)
        if not intl_part.empty:
            intl_part["notes"] = "yfinance (consolidated)"
        parts.append(intl_part)

    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=_RESULT_COLS)
    df = pd.concat(parts, ignore_index=True).drop_duplicates(subset="symbol")
    return df.sort_values("rvol", ascending=False).reset_index(drop=True)


def scan(tickers: list[str], cfg: ScanConfig | None = None, progress=None) -> pd.DataFrame:
    """End-of-day scan: ranked DataFrame of unusual volume, with retry on throttling."""
    return _run(tickers, cfg, intraday=False, progress=progress)


# --- Intraday (time-of-day adjusted) -------------------------------------------


def _intraday_metrics(df: pd.DataFrame, ticker: str, cfg: ScanConfig) -> dict | None:
    """Compare today's cumulative volume *so far* against the average cumulative
    volume by the same time-of-day on prior sessions (the correct intraday RVOL).
    """
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Volume", "Close"])
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None

    day = pd.Index([ts.date() for ts in df.index])
    tod = pd.Index([ts.strftime("%H:%M") for ts in df.index])  # zero-padded, sortable
    close_vals = df["Close"].astype(float).values
    open_vals = (df["Open"] if "Open" in df.columns else df["Close"]).astype(float).values
    high_vals = (df["High"] if "High" in df.columns else df["Close"]).astype(float).values
    low_vals = (df["Low"] if "Low" in df.columns else df["Close"]).astype(float).values
    work = pd.DataFrame(
        {"vol": df["Volume"].astype(float).values,
         "close": close_vals,
         "open": open_vals,
         "high": high_vals,
         "low": low_vals,
         "day": day, "tod": tod},
        index=range(len(df)),
    )
    work["cum"] = work.groupby("day")["vol"].cumsum()

    days = sorted(work["day"].unique())
    if len(days) < 4:  # need today + a few baseline sessions
        return None
    today = days[-1]
    prev_day = days[-2]

    today_rows = work[work["day"] == today]
    if today_rows.empty:
        return None
    as_of = today_rows["tod"].iloc[-1]
    today_cum = float(today_rows["cum"].iloc[-1])
    last_open = float(today_rows["open"].iloc[0])
    last_close = float(today_rows["close"].iloc[-1])
    if today_cum <= 0:
        return None

    # Cumulative volume by the same time-of-day on each prior session.
    baseline: list[float] = []
    for d in days[:-1]:
        g = work[(work["day"] == d) & (work["tod"] <= as_of)]
        if not g.empty:
            baseline.append(float(g["cum"].iloc[-1]))
    if len(baseline) < 3:
        return None

    s = pd.Series(baseline)
    avg = float(s.mean())
    std = float(s.std())
    avg10 = float(s.iloc[-10:].mean())  # last 10 sessions at this time-of-day
    if avg <= 0:
        return None

    prev_cum = baseline[-1]  # previous session's cumulative at this time-of-day
    prev_rows = work[work["day"] == prev_day]
    prev_close = float(prev_rows["close"].iloc[-1]) if not prev_rows.empty else last_close
    pct_change = (last_close / prev_close - 1.0) * 100.0 if prev_close else float("nan")

    rvol = today_cum / avg
    zscore = (today_cum - avg) / std if std > 0 else float("nan")
    dollar_vol = today_cum * last_close

    # --- Intraday volatility (today's high-low swing so far) ----------------
    day_high = float(today_rows["high"].max())
    day_low = float(today_rows["low"].min())
    day_range_pct = (day_high - day_low) / last_close * 100.0 if last_close else float("nan")
    # vs. the typical full-day range on prior sessions
    prior = work[work["day"] != today]
    if not prior.empty:
        per_day = prior.groupby("day").agg(hi=("high", "max"), lo=("low", "min"))
        avg_range = float((per_day["hi"] - per_day["lo"]).mean())
    else:
        avg_range = float("nan")
    range_vs_avg = (day_high - day_low) / avg_range if avg_range and avg_range > 0 else float("nan")

    # --- True up vs. down volume (we have every bar here) -------------------
    # Classify each bar as buying (close >= open) or selling (close < open) and
    # sum the volume — a real measured split, not the daily-bar approximation.
    up_mask = today_rows["close"].values >= today_rows["open"].values
    up_vol = float(today_rows["vol"].values[up_mask].sum())
    down_vol = float(today_rows["vol"].values[~up_mask].sum())
    traded = up_vol + down_vol
    buy_vol_pct = up_vol / traded * 100.0 if traded > 0 else float("nan")
    if math.isnan(buy_vol_pct):
        flow = "mixed"
    elif buy_vol_pct >= 60.0:
        flow = "bought up"
    elif buy_vol_pct <= 40.0:
        flow = "sold off"
    else:
        flow = "mixed"

    return {
        "symbol": ticker,
        "date": f"{today.isoformat()} {as_of}",
        "avg_volume": int(avg),
        "last_volume": int(today_cum),
        "prev_volume": int(prev_cum),
        "avg_volume_10d": int(avg10),
        "rvol": round(rvol, 2),
        "open": round(last_open, 4),
        "close": round(last_close, 4),
        "pct_change": round(pct_change, 2),
        "day_range_pct": round(day_range_pct, 2) if not math.isnan(day_range_pct) else None,
        "range_vs_avg": round(range_vs_avg, 2) if not math.isnan(range_vs_avg) else None,
        "buy_vol_pct": round(buy_vol_pct, 1) if not math.isnan(buy_vol_pct) else None,
        "flow": flow,
        "vol_zscore": round(zscore, 2) if not math.isnan(zscore) else None,
        "dollar_vol": int(dollar_vol),
        "direction": "up" if pct_change > 0 else ("down" if pct_change < 0 else "flat"),
        "notes": "",
    }


def scan_intraday(tickers: list[str], cfg: ScanConfig | None = None, progress=None) -> pd.DataFrame:
    """Intraday volume scan (yfinance ~15-min-delayed bars, or Alpaca if configured)."""
    return _run(tickers, cfg, intraday=True, progress=progress)
