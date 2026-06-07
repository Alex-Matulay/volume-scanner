# Unusual Volume Scanner

End-of-day scanner that flags US stocks trading on **unusually high volume** vs.
their own recent average — the classic "something is happening here" signal.

**📊 Live results — two pages, cross-linked at the top of each:**
- 👉 **Daily (EOD):** https://alex-matulay.github.io/volume-scanner/ — rebuilt every weekday after the US close.
- ⚡ **Intraday:** https://alex-matulay.github.io/volume-scanner/intraday.html — refreshed **every 30 minutes during US market hours**.

Each symbol on both pages links straight to its Yahoo Finance chart.

---

## How it works

- **Daily page** — a scheduled GitHub Action
  ([`.github/workflows/eod-scan.yml`](.github/workflows/eod-scan.yml)) runs at
  **22:00 UTC on weekdays** (~6pm US Eastern, after EOD data settles). It screens
  the whole US universe fast via the free **Alpaca** API, then re-measures the
  candidates on **consolidated volume** (so the figures match Yahoo / your
  broker).
- **Intraday page** — a second Action
  ([`.github/workflows/intraday-scan.yml`](.github/workflows/intraday-scan.yml))
  runs **every 30 min, 13:00–21:00 UTC on weekdays** (US market hours). It
  compares today's cumulative volume against the average for the *same
  time-of-day* on prior sessions (proper intraday RVOL). To stay fast across
  many runs it uses Alpaca's free **IEX** feed directly — the **RVOL ratio is the
  signal**, while absolute share counts are a fraction of total.
- Both pages publish to the **`gh-pages`** branch (`keep_files` preserves the
  other page), which GitHub Pages serves.
- You can also trigger either manually from the **Actions** tab → *Run workflow*.

## Metrics shown

| Column | Meaning |
|---|---|
| `RVOL` | Relative volume = day's volume / 20-day average. 3× = three times normal. |
| `Avg vol` | 20-day average volume (the RVOL baseline). |
| `Day vol` | That day's total volume. |
| `Prev-day vol` | Previous day's total volume. |
| `Avg vol 10d` | Trailing 10-day average volume. |
| `Open` / `Close` | Day's open and close. |
| `% chg` | Close vs. previous close. |
| `Range` | The day's high–low swing as % of price — how volatile the stock was through the day. |
| `Vol vs avg` | That swing vs. the stock's average daily range (e.g. `2.1×` = twice as volatile as normal). |

The page itself also carries a collapsible **"What the columns mean"** legend above the table.

## Run it yourself locally

```bash
pip install -r volume_scanner/requirements.txt

# fast US scan via Alpaca (needs free API keys — see volume_scanner/README.md)
python -m volume_scanner.cli --source alpaca --market us --min-rvol 3 \
  --html site/index.html --out report.csv

# or the interactive dashboard
streamlit run volume_scanner/dashboard.py
```

Full CLI docs, flags, the Alpaca free-key walkthrough, and notes/limitations are
in [`volume_scanner/README.md`](volume_scanner/README.md).

## Setup for the daily auto-scan (one time)

1. Repo **Settings → Secrets and variables → Actions** → add:
   - `APCA_API_KEY_ID`
   - `APCA_API_SECRET_KEY`
2. Repo **Settings → Actions → General → Workflow permissions** → **Read and
   write permissions** (so the workflows can push to `gh-pages`).
3. Run either workflow once (Actions tab → *Run workflow*) to create the
   **`gh-pages`** branch, then **Settings → Pages** → *Build and deployment* →
   Source = **Deploy from a branch** → Branch = **`gh-pages`** / **`/ (root)`**.
4. The schedules then run on their own; or trigger them manually any time.

> Educational tool, not financial advice. The daily page is end-of-day; the
> intraday page uses the free IEX feed (partial volume — RVOL ratio is the signal).
