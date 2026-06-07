"""Command-line end-of-day volume scanner.

Examples:
  python -m volume_scanner.cli --market us --top 25
  python -m volume_scanner.cli --market all --min-rvol 3 --out report.csv
  python -m volume_scanner.cli --symbols-file my_list.csv

Run from the repo root (the folder that contains the volume_scanner/ directory).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from . import universe
from .scanner import ScanConfig, scan, scan_intraday


def _fmt_int(n) -> str:
    return f"{int(n):,}" if n is not None else "-"


def _fmt_pct(v, dp: int = 1) -> str:
    try:
        f = float(v)
        return "-" if f != f else f"{f:.{dp}f}%"  # f != f -> NaN
    except (TypeError, ValueError):
        return "-"


def _fmt_x(v) -> str:
    try:
        f = float(v)
        return "-" if f != f else f"{f:.1f}x"
    except (TypeError, ValueError):
        return "-"


# Short, human-readable explanation of every column shown, printed above the
# table and rendered as a legend on the HTML page.
COLUMN_HELP = [
    ("symbol", "Ticker symbol."),
    ("date", "Trading day (intraday mode adds the time-of-day)."),
    ("avg_vol", "20-day average daily volume - the RVOL baseline."),
    ("day_vol", "That day's total volume."),
    ("prev_vol", "Previous day's total volume."),
    ("avg_vol_10d", "Trailing 10-day average volume."),
    ("rvol", "Relative volume = day_vol / avg_vol (3.0 = 3x normal)."),
    ("open", "Day's opening price."),
    ("close", "Day's closing price."),
    ("%chg", "Close vs. the previous day's close."),
    ("range%", "Day's high-low swing as % of price - intraday volatility."),
    ("vol_x", "That swing vs. the stock's average daily range (2.0 = twice as volatile as usual)."),
    ("earnings", "Latest quarterly earnings summary (only with --earnings)."),
]


def _print_legend(has_earn: bool) -> None:
    print("\nColumns:")
    for name, desc in COLUMN_HELP:
        if name == "earnings" and not has_earn:
            continue
        print(f"  {name.ljust(13)} {desc}")


def _print_table(df, top: int, intraday: bool = False) -> None:
    if df.empty:
        print("\nNo stocks matched the filters.")
        return
    view = df.head(top)
    has_earn = "earnings_note" in df.columns
    _print_legend(has_earn)
    cols = ["symbol", "date", "avg_volume", "last_volume", "prev_volume",
            "avg_volume_10d", "rvol", "open"]
    # Intraday drops the point-in-time price columns (they shift through the day).
    if not intraday:
        cols += ["close", "pct_change", "day_range_pct", "range_vs_avg"]
    if has_earn:
        cols.append("earnings_note")
    labels = {"symbol": "symbol", "date": "date", "avg_volume": "avg_vol",
              "last_volume": "day_vol", "prev_volume": "prev_vol",
              "avg_volume_10d": "avg_vol_10d", "rvol": "rvol", "open": "open",
              "close": "close", "pct_change": "%chg", "day_range_pct": "range%",
              "range_vs_avg": "vol_x", "earnings_note": "earnings"}
    widths = {"symbol": 9, "date": 19, "avg_volume": 14, "last_volume": 14,
              "prev_volume": 14, "avg_volume_10d": 14, "rvol": 7, "open": 10,
              "close": 10, "pct_change": 9, "day_range_pct": 8, "range_vs_avg": 7,
              "earnings_note": 52}
    header = "".join(labels[c].ljust(widths[c]) for c in cols)
    print("\n" + header)
    print("-" * len(header))
    for _, r in view.iterrows():
        line = (
            str(r["symbol"]).ljust(widths["symbol"])
            + str(r["date"]).ljust(widths["date"])
            + _fmt_int(r["avg_volume"]).ljust(widths["avg_volume"])
            + _fmt_int(r["last_volume"]).ljust(widths["last_volume"])
            + _fmt_int(r["prev_volume"]).ljust(widths["prev_volume"])
            + _fmt_int(r["avg_volume_10d"]).ljust(widths["avg_volume_10d"])
            + f"{r['rvol']:.2f}".ljust(widths["rvol"])
            + f"{r['open']:.2f}".ljust(widths["open"])
        )
        if not intraday:
            line += (
                f"{r['close']:.2f}".ljust(widths["close"])
                + f"{r['pct_change']:+.2f}%".ljust(widths["pct_change"])
                + _fmt_pct(r.get("day_range_pct")).ljust(widths["day_range_pct"])
                + _fmt_x(r.get("range_vs_avg")).ljust(widths["range_vs_avg"])
            )
        if has_earn:
            line += str(r.get("earnings_note", "")).ljust(widths["earnings_note"])
        print(line)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="End-of-day unusual-volume stock scanner.")
    p.add_argument("--market", default="us", choices=["us", "uk", "eu", "all"],
                   help="Which universe to scan (default: us).")
    p.add_argument("--symbols-file", help="CSV with a 'symbol' column to scan instead.")
    p.add_argument("--lookback", type=int, default=20, help="Baseline length in days.")
    p.add_argument("--period", default="3mo", help="History window to pull (yfinance).")
    p.add_argument("--min-rvol", type=float, default=2.0, help="Minimum relative volume.")
    p.add_argument("--min-dollar-vol", type=float, default=1_000_000.0,
                   help="Minimum last-day dollar volume.")
    p.add_argument("--min-avg-vol", type=float, default=50_000.0,
                   help="Minimum average baseline volume. Lower it (e.g. 0) for "
                        "intraday/IEX scans where cumulative volume is partial.")
    p.add_argument("--chunk-size", type=int, default=100, help="Tickers per batch.")
    p.add_argument("--pause", type=float, default=1.0,
                   help="Seconds to wait between batches (raise if rate-limited).")
    p.add_argument("--max-retries", type=int, default=4,
                   help="Retry rounds over rate-limited tickers.")
    p.add_argument("--no-threads", action="store_true",
                   help="Download sequentially (gentler on Yahoo's rate limit).")
    p.add_argument("--source", default="yfinance", choices=["yfinance", "alpaca"],
                   help="Data backend. 'alpaca' is fast (US only); UK/EU fall back to yfinance.")
    p.add_argument("--alpaca-key", help="Alpaca API key id (or set APCA_API_KEY_ID).")
    p.add_argument("--alpaca-secret", help="Alpaca API secret (or set APCA_API_SECRET_KEY).")
    p.add_argument("--alpaca-feed", default="iex", choices=["iex", "sip"],
                   help="Alpaca data feed (free plans = iex).")
    p.add_argument("--no-enrich", action="store_true",
                   help="Don't re-measure Alpaca hits on accurate yfinance volume. "
                        "Faster, but volume figures stay IEX-only (understated).")
    p.add_argument("--save-keys", action="store_true",
                   help="Save the provided --alpaca-key/--alpaca-secret for future runs, then continue.")
    p.add_argument("--intraday", action="store_true",
                   help="Intraday mode: time-of-day adjusted RVOL from free ~15min-delayed bars.")
    p.add_argument("--intraday-interval", default="5m",
                   help="Intraday bar size: 1m,2m,5m,15m,30m,60m (default 5m).")
    p.add_argument("--intraday-period", default="10d",
                   help="Intraday history window (5m bars: max ~60d).")
    p.add_argument("--include-etfs", action="store_true", help="Include US ETFs.")
    p.add_argument("--earnings", action="store_true",
                   help="After scanning, look up each flagged stock's latest "
                        "quarterly earnings and flag record-quarter results "
                        "(revenue high, YoY growth, EPS surprise, earnings date).")
    p.add_argument("--top", type=int, default=25, help="Rows to print.")
    p.add_argument("--out", help="Write full results to this CSV path.")
    p.add_argument("--html", help="Write a static HTML report (with Yahoo chart "
                   "links) to this path, e.g. site/index.html for GitHub Pages.")
    p.add_argument("--limit", type=int, help="Cap universe size (for quick tests).")
    args = p.parse_args(argv)

    if args.save_keys:
        if not (args.alpaca_key and args.alpaca_secret):
            p.error("--save-keys requires --alpaca-key and --alpaca-secret.")
        from . import sources
        path = sources.save_credentials(args.alpaca_key, args.alpaca_secret)
        print(f"Saved Alpaca credentials -> {path}")

    if args.symbols_file:
        tickers = universe.load_csv(args.symbols_file)
        src = args.symbols_file
    else:
        print(f"Building '{args.market}' universe...", flush=True)
        tickers = universe.build_universe(args.market, include_etfs=args.include_etfs)
        src = args.market

    if args.limit:
        tickers = tickers[: args.limit]
    print(f"Scanning {len(tickers):,} tickers from {src} ...", flush=True)

    cfg = ScanConfig(
        lookback_days=args.lookback,
        period=args.period,
        chunk_size=args.chunk_size,
        min_dollar_vol=args.min_dollar_vol,
        min_avg_vol=args.min_avg_vol,
        min_rvol=args.min_rvol,
        intraday_interval=args.intraday_interval,
        intraday_period=args.intraday_period,
        pause_between_chunks=args.pause,
        max_retry_rounds=args.max_retries,
        threads=not args.no_threads,
        source=args.source,
        alpaca_key=args.alpaca_key,
        alpaca_secret=args.alpaca_secret,
        alpaca_feed=args.alpaca_feed,
        enrich=not args.no_enrich,
    )
    if args.source == "alpaca":
        print("Source: Alpaca (US). Non-US symbols fall back to yfinance.", flush=True)

    start = time.time()

    def progress(done, total):
        pct = done / total * 100 if total else 100
        print(f"  {done:,}/{total:,} ({pct:4.1f}%)", end="\r", flush=True)

    from .sources import AlpacaAuthError
    try:
        if args.intraday:
            print(f"Intraday mode ({args.intraday_interval} bars).", flush=True)
            df = scan_intraday(tickers, cfg, progress=progress)
        else:
            df = scan(tickers, cfg, progress=progress)
    except AlpacaAuthError as e:
        print(f"\nAlpaca credentials problem: {e}")
        return 2
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s. {len(df):,} stocks with unusual volume.")

    if args.earnings and not df.empty:
        from . import earnings as earnings_mod

        def eprog(done, total):
            print(f"  earnings {done:,}/{total:,}", end="\r", flush=True)

        print("Checking quarterly earnings for flagged stocks...", flush=True)
        df = earnings_mod.annotate(df, pause=0.0, progress=eprog)
        n_rec = int(df["record_quarter"].fillna(False).sum())
        n_near = int(df["near_spike"].fillna(False).sum())
        print(f"\n  {n_rec} with record-quarter revenue; "
              f"{n_near} spiked right after earnings.")

    _print_table(df, args.top, intraday=args.intraday)

    if args.out:
        import os
        d = os.path.dirname(args.out)
        if d:
            os.makedirs(d, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"\nSaved {len(df):,} rows -> {args.out}")
    else:
        default = f"volume_scan_{datetime.now():%Y%m%d_%H%M}.csv"
        df.to_csv(default, index=False)
        print(f"\nSaved {len(df):,} rows -> {default}")

    if args.html:
        import os
        from . import report_html
        d = os.path.dirname(args.html)
        if d:
            os.makedirs(d, exist_ok=True)
        report_html.write(df, args.html, market=src, min_rvol=args.min_rvol,
                          mode="intraday" if args.intraday else "eod")
        print(f"Saved HTML report -> {args.html}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
