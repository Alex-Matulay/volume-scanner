# Unusual Volume Scanner (US + UK + EU)

End-of-day scanner that flags stocks trading on **unusually high volume** vs.
their own recent average — the classic "something is happening here" signal.
Comes as a **CLI + CSV report** and a **Streamlit dashboard**.

> Educational tool, not financial advice. Data is end-of-day from Yahoo Finance.

## What it measures

For each stock, comparing the most recent trading day to a trailing baseline:

| Metric | Meaning |
|---|---|
| `rvol` | Relative volume = last day's volume / average of prior N days. **RVOL 2 = twice normal.** |
| `vol_zscore` | How many standard deviations above the baseline the last volume is. |
| `pct_change` | Last close % change vs. the previous close. |
| `dollar_vol` | last volume × last close — used to filter out illiquid names. |
| `direction` | up / down / flat based on the price move. |

Results are ranked by `rvol` (biggest volume anomalies first).

## Install

```bash
pip install -r volume_scanner/requirements.txt
```

(Needs a recent `yfinance` — older versions break against Yahoo's current API.)

## CLI usage

Run from the **repo root** (the folder containing `volume_scanner/`):

```bash
# Quick US scan, top 25 by RVOL
python -m volume_scanner.cli --market us --top 25

# Whole universe (US + UK + EU), only big spikes, save to CSV
python -m volume_scanner.cli --market all --min-rvol 3 --out report.csv

# Scan your own watchlist (CSV with a "symbol" column)
python -m volume_scanner.cli --symbols-file my_list.csv

# Fast test run (cap the universe)
python -m volume_scanner.cli --market us --limit 200
```

Key flags: `--market {us,uk,eu,all}`, `--min-rvol`, `--min-dollar-vol`,
`--lookback` (baseline days, default 20), `--period` (history pulled),
`--limit` (cap universe for quick tests), `--include-etfs`, `--out`.

A timestamped CSV is always written even if `--out` is omitted.

## Dashboard

```bash
streamlit run volume_scanner/dashboard.py
```

Sidebar controls the market, min RVOL, baseline length, liquidity filter, and a
universe cap. Results show as a sortable table with summary metrics, a CSV
download, and per-ticker price + volume charts.

## The ticker universe

- **US** — fetched live from the public NASDAQ Trader symbol directory
  (NASDAQ + NYSE/AMEX, ~7,400 common stocks), cached to `data/us_symbols.csv`.
  Delete that file to refresh.
- **UK + EU** — curated large-cap constituents (FTSE 100, DAX 40, CAC 40, AEX,
  IBEX, FTSE MIB) using Yahoo exchange suffixes (`.L`, `.DE`, `.PA`, …).

There is **no public, complete list of every Trading212 instrument** and no
public T212 market-data API, so this is a practical superset of the most-traded
names rather than a literal T212 mirror. To scan an exact T212 watchlist, export
your symbols to a CSV (one `symbol` column, Yahoo-style tickers) and use
`--symbols-file`.

## Faster US scans with Alpaca (free)

yfinance is fine but Yahoo throttles bulk scans. **Alpaca's free API** returns
hundreds of symbols per request, so a full US scan finishes in well under a
minute instead of 15+ paced minutes.

### Get a free Alpaca API key (no credit card)

1. Go to **https://alpaca.markets** and click **Sign up** (a "Paper" trading
   account is free and enough — you do NOT need to fund anything).
2. Verify your email and log in to the dashboard.
3. Make sure you're on the **Paper Trading** account (toggle, top-left).
4. On the right-hand panel find **API Keys** → **Generate New Keys**.
5. Copy the **Key ID** and the **Secret Key** (the secret is shown only once).

### Use the key

Save it once (stored in `data/alpaca_keys.json`, which is git-ignored):

```bash
python -m volume_scanner.cli --source alpaca \
  --alpaca-key YOUR_KEY_ID --alpaca-secret YOUR_SECRET --save-keys --limit 5
```

Then every later run just needs `--source alpaca`:

```bash
python -m volume_scanner.cli --source alpaca --market us --min-rvol 3 --out report.csv
```

Alternatively set environment variables instead of saving a file:
`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`.

**Notes on Alpaca:**
- **US stocks only.** When `--source alpaca` is used with `--market all`, US
  symbols go to Alpaca and UK/EU symbols automatically fall back to yfinance.
- Free plans use the **IEX feed** — a subset of total volume. Relative volume
  (today vs. baseline) is still meaningful, but absolute volume and `dollar_vol`
  are understated, so you may want a lower `--min-dollar-vol` (e.g. `100000`).

## Notes & limitations

- **End-of-day only.** For live intraday RVOL you'd need a real-time data
  provider (Polygon, Alpaca, IBKR) — not included here.
- LSE (`.L`) prices are quoted in **pence**, so `dollar_vol` for UK names is in
  pence-volume and isn't directly comparable to USD names. RVOL/z-score are
  currency-agnostic and rank correctly regardless.
- Yahoo data can have gaps or the odd bad print; treat outputs as a **starting
  watchlist to investigate**, not a trade trigger.
- A full `--market all` scan downloads thousands of tickers and takes several
  minutes. Use `--limit` while experimenting.
