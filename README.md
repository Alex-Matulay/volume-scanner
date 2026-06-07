# Unusual Volume Scanner

End-of-day scanner that flags US stocks trading on **unusually high volume** vs.
their own recent average — the classic "something is happening here" signal.

**📊 Live results (rebuilt automatically every weekday after the US close):**
👉 https://alex-matulay.github.io/volume-scanner/

Each symbol on the page links straight to its Yahoo Finance chart.

---

## How it works

- A scheduled GitHub Action ([`.github/workflows/eod-scan.yml`](.github/workflows/eod-scan.yml))
  runs at **22:00 UTC on weekdays** (~6pm US Eastern, after EOD data settles).
- It screens the whole US universe fast via the free **Alpaca** API, then
  re-measures the candidates on **consolidated volume** (so the figures match
  Yahoo / your broker), and publishes a static page to **GitHub Pages**.
- You can also trigger it manually from the **Actions** tab → *EOD Volume Scan*
  → *Run workflow*.

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
| `Buy vol` | Estimated share of volume that was buying. Daily mode infers it from where the close landed in the day's range; intraday mode measures it directly (volume on up-bars vs down-bars). |
| `Flow` | `bought up` / `sold off` / `mixed` — was the volume mostly accumulation or distribution. Distinct from `% chg`: a stock can close down on the day yet still be `bought up` if it rallied off its lows. |
| `Notes` | Data source / quality tag. |

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
2. Repo **Settings → Pages** → *Build and deployment* → Source = **GitHub Actions**.
3. The schedule then runs on its own; or trigger it manually from the Actions tab.

> Educational tool, not financial advice. Data is end-of-day.
