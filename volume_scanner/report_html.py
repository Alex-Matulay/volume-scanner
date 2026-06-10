"""Render scan results as a self-contained static HTML page.

The page has no external dependencies (inline CSS + a little vanilla JS for
click-to-sort), so it can be served as-is by GitHub Pages. Every symbol links
to its Yahoo Finance quote/chart page so you can open a chart in one click.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone


def _yahoo_url(symbol: str) -> str:
    # Our symbols are already in Yahoo format (US plain, intl with .L/.DE/...).
    return f"https://finance.yahoo.com/quote/{symbol}"


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "-"


def _fmt_num(v, dp: int = 2) -> str:
    try:
        f = float(v)
        return "-" if f != f else f"{f:,.{dp}f}"  # f != f -> NaN
    except (TypeError, ValueError):
        return "-"


def _rows_html(df, *, intraday: bool, has_earn: bool, n_cols: int) -> str:
    """Render the <tbody> rows. Shared by the static page and the JSON payload
    the page polls, so refreshed rows are formatted identically."""
    rows_html = []
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            sym = str(r["symbol"])
            url = _yahoo_url(sym)
            pct = r.get("pct_change")
            try:
                pct_f = float(pct)
            except (TypeError, ValueError):
                pct_f = 0.0
            cls = "up" if pct_f > 0 else ("down" if pct_f < 0 else "flat")
            pct_str = f"{pct_f:+.2f}%"

            # Volatility: day's range + range vs. the stock's normal range.
            rng = _fmt_num(r.get("day_range_pct"), 1)
            rng_str = "-" if rng == "-" else rng + "%"
            volx = _fmt_num(r.get("range_vs_avg"), 1)
            volx_str = "-" if volx == "-" else volx + "×"
            earn_cell = ""
            if has_earn:
                etxt = html.escape(str(r.get("earnings_note", "") or ""))
                record = bool(r.get("record_quarter"))
                near = bool(r.get("near_spike"))
                ecls = "earn"
                if record:
                    ecls += " record"
                elif near:
                    ecls += " near"
                badge = "\U0001F525 " if record else ("⚡ " if near else "")
                earn_cell = f'<td class="{ecls}">{badge}{etxt}</td>'
            # Intraday omits the point-in-time price columns (close/%chg/range/
            # vol-vs-avg) since they keep moving through the session.
            price_cells = "" if intraday else (
                f'<td class="num">{_fmt_num(r.get("close"))}</td>'
                f'<td class="num {cls}">{pct_str}</td>'
                f'<td class="num">{rng_str}</td>'
                f'<td class="num">{volx_str}</td>'
            )
            rows_html.append(
                "<tr>"
                f'<td class="sym"><a href="{url}" target="_blank" rel="noopener">{html.escape(sym)} ↗</a></td>'
                f'<td>{html.escape(str(r.get("date", "")))}</td>'
                f'<td class="num rvol">{_fmt_num(r.get("rvol"))}×</td>'
                f'<td class="num">{_fmt_int(r.get("avg_volume"))}</td>'
                f'<td class="num">{_fmt_int(r.get("last_volume"))}</td>'
                f'<td class="num">{_fmt_int(r.get("prev_volume"))}</td>'
                f'<td class="num">{_fmt_int(r.get("avg_volume_10d"))}</td>'
                f'<td class="num">{_fmt_num(r.get("open"))}</td>'
                f'{price_cells}'
                f'{earn_cell}'
                "</tr>"
            )
    return "\n".join(rows_html) or (
        f'<tr><td colspan="{n_cols}" class="empty">No stocks matched the filters '
        "for this run.</td></tr>"
    )


def payload(df, *, market: str = "us", min_rvol: float = 3.0,
            generated_at: datetime | None = None, mode: str = "eod") -> dict:
    """JSON-serializable snapshot the static page polls to refresh in place."""
    generated_at = generated_at or datetime.now(timezone.utc)
    intraday = mode == "intraday"
    has_earn = df is not None and "earnings_note" in df.columns
    n_cols = (8 if intraday else 12) + (1 if has_earn else 0)
    return {
        "generated_ms": int(generated_at.timestamp() * 1000),
        "generated": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "market": market,
        "min_rvol": float(min_rvol),
        "mode": mode,
        "n": 0 if df is None else int(len(df)),
        "rows_html": _rows_html(df, intraday=intraday, has_earn=has_earn,
                                n_cols=n_cols),
    }


def render(df, *, market: str = "us", min_rvol: float = 3.0,
           generated_at: datetime | None = None, mode: str = "eod",
           data_url: str | None = None) -> str:
    """Return a full HTML document string for the given results DataFrame.

    mode: "eod" (end-of-day) or "intraday" (refreshed through the session).
    The two pages live side by side (index.html / intraday.html) and cross-link.
    data_url: relative URL of the JSON snapshot the page should poll to
    refresh itself in place (None disables auto-refresh).
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    gen_epoch_ms = int(generated_at.timestamp() * 1000)  # for the live freshness badge
    js_intraday = "true" if mode == "intraday" else "false"
    js_data_url = json.dumps(data_url)  # 'null' or '"intraday.json"'
    n = 0 if df is None else len(df)

    intraday = mode == "intraday"
    page_title = "Intraday Volume Scanner" if intraday else "Unusual Volume Scanner"
    page_emoji = "⚡" if intraday else "\U0001F4C8"
    if intraday:
        blurb = ("Live during the US session: today's cumulative volume so far vs. "
                 "the 20-day average daily volume — so RVOL builds through the day "
                 "(3× = already 3× a normal full day) and converges with the daily "
                 "scan at the close. Figures are consolidated (match TradingView / "
                 "brokers).")
    else:
        blurb = ('Volume is end-of-day; figures tagged "consolidated" match '
                 "Yahoo / brokers.")
    # Cross-link nav (active tab highlighted).
    nav_html = (
        '<nav class="tabs">'
        f'<a class="{"active" if not intraday else ""}" href="index.html">\U0001F4C8 Daily (EOD)</a>'
        f'<a class="{"active" if intraday else ""}" href="intraday.html">⚡ Intraday</a>'
        "</nav>"
    )

    has_earn = df is not None and "earnings_note" in df.columns
    # Intraday drops the point-in-time price columns (close/%chg/range/vol-vs-avg)
    # since they keep changing through the session; it keeps the volume metrics.
    base_cols = 8 if intraday else 12  # symbol..open (+price cols for EOD)
    n_cols = base_cols + (1 if has_earn else 0)

    body_rows = _rows_html(df, intraday=intraday, has_earn=has_earn, n_cols=n_cols)
    earn_header = "<th>Earnings</th>" if has_earn else ""
    price_headers = "" if intraday else (
        '<th class="num">Close</th>'
        '<th class="num">% chg</th>'
        '<th class="num">Range</th>'
        '<th class="num">Vol vs avg</th>'
    )

    # Legend: a short explanation of every column, shown above the table.
    if intraday:
        legend_items = [
            ("Symbol", "Ticker (click to open its Yahoo Finance chart)."),
            ("Date", "Trading day and time-of-day the snapshot was taken."),
            ("RVOL", "Today's cumulative volume so far / the 20-day average daily "
                     "volume. Builds through the session — 3× = already 3× a normal "
                     "full day's volume (converges with the daily scan at the close)."),
            ("Avg vol", "20-day average daily volume — the RVOL baseline."),
            ("Day vol", "Today's cumulative volume so far."),
            ("Prev-day vol", "Previous session's full-day volume."),
            ("Avg vol 10d", "Trailing 10-day average daily volume."),
            ("Open", "Today's opening price."),
        ]
    else:
        legend_items = [
            ("Symbol", "Ticker (click to open its Yahoo Finance chart)."),
            ("Date", "Trading day."),
            ("RVOL", "Relative volume = day volume / 20-day average (3× = 3× normal)."),
            ("Avg vol", "20-day average daily volume — the RVOL baseline."),
            ("Day vol", "That day's total volume."),
            ("Prev-day vol", "Previous day's total volume."),
            ("Avg vol 10d", "Trailing 10-day average volume."),
            ("Open / Close", "Day's opening and closing price."),
            ("% chg", "Close vs. the previous day's close."),
            ("Range", "Day's high-low swing as % of price — intraday volatility."),
            ("Vol vs avg", "That swing vs. the stock's average daily range (2× = twice as volatile as usual)."),
        ]
    if has_earn:
        legend_items.append(
            ("Earnings", "Latest quarterly earnings summary; \U0001F525 = record-quarter revenue, ⚡ = spike right after earnings."))
    legend_html = "\n".join(
        f"<li><b>{html.escape(k)}</b> — {html.escape(v)}</li>" for k, v in legend_items
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(page_title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 1.5rem; background: #0f1115; color: #e6e6e6; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.4rem; }}
  nav.tabs {{ display: flex; gap: .5rem; margin: .25rem 0 .9rem; }}
  nav.tabs a {{ padding: .35rem .8rem; border-radius: 999px; text-decoration: none;
                font-size: .85rem; font-weight: 600; color: #9aa4b2;
                border: 1px solid #232733; background: #12151c; }}
  nav.tabs a:hover {{ color: #cfd6e0; border-color: #2c3140; }}
  nav.tabs a.active {{ color: #0f1115; background: #6ea8fe; border-color: #6ea8fe; }}
  .meta {{ color: #9aa4b2; font-size: .85rem; margin-bottom: 1rem; }}
  .meta b {{ color: #cfd6e0; }}
  .wrap {{ overflow-x: auto; border: 1px solid #232733; border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
  th, td {{ padding: .55rem .7rem; text-align: left; white-space: nowrap;
            border-bottom: 1px solid #1c2029; }}
  th {{ position: sticky; top: 0; background: #161a22; cursor: pointer;
        user-select: none; font-weight: 600; }}
  th:hover {{ background: #1d2230; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr:hover td {{ background: #141821; }}
  .sym a {{ color: #6ea8fe; text-decoration: none; font-weight: 600; }}
  .sym a:hover {{ text-decoration: underline; }}
  .rvol {{ font-weight: 700; color: #ffd479; }}
  .up {{ color: #4ade80; }}
  .down {{ color: #f87171; }}
  .flat {{ color: #9aa4b2; }}
  details.legend {{ margin: 0 0 1rem; border: 1px solid #232733; border-radius: 10px;
                    background: #12151c; padding: .4rem .9rem; }}
  details.legend summary {{ cursor: pointer; color: #cfd6e0; font-weight: 600;
                            font-size: .9rem; padding: .35rem 0; }}
  details.legend ul {{ margin: .4rem 0 .6rem; padding-left: 1.1rem;
                       color: #9aa4b2; font-size: .82rem; line-height: 1.6; }}
  details.legend b {{ color: #cfd6e0; }}
  .earn {{ color: #b6c0cf; font-size: .8rem; white-space: normal; min-width: 22rem; }}
  .earn.record {{ color: #ffd479; font-weight: 600; }}
  .earn.near {{ color: #7dd3fc; }}
  .empty {{ text-align: center; color: #9aa4b2; padding: 2rem; }}
  footer {{ margin-top: 1rem; color: #6b7280; font-size: .78rem; }}
  a.ext {{ color: #6ea8fe; }}
  .freshness {{ display: inline-flex; align-items: center; gap: .4rem;
                padding: .25rem .7rem; border-radius: 999px; font-size: .82rem;
                font-weight: 600; border: 1px solid transparent; }}
  .freshness::before {{ content: ""; width: .55rem; height: .55rem;
                        border-radius: 50%; background: currentColor; }}
  .freshness.fresh-ok {{ color: #4ade80; background: #102417; border-color: #1e4d2f; }}
  .freshness.fresh-warn {{ color: #fbbf24; background: #2a2310; border-color: #574716; }}
  .freshness.fresh-bad {{ color: #f87171; background: #2a1313; border-color: #5a2020; }}
  .freshness.fresh-idle {{ color: #9aa4b2; background: #161a22; border-color: #2c3140; }}
  .times {{ color: #9aa4b2; font-size: .82rem; margin-left: .6rem; }}
  .mkthours {{ color: #9aa4b2; font-size: .82rem; margin: 0 0 1rem; }}
  .mkthours b {{ color: #cfd6e0; }}
</style>
</head>
<body>
  <h1>{page_emoji} {html.escape(page_title)}</h1>
  {nav_html}
  <div style="margin: .2rem 0 .5rem;">
    <span id="freshness" class="freshness fresh-idle">checking freshness…</span>
    <span id="uptimes" class="times"></span>
  </div>
  <div class="mkthours">
    \U0001F4C5 <b>US market open:</b> Mon–Fri, 9:30 AM – 4:00 PM New York time
    (≈ 2:30 PM – 9:00 PM London · 13:30 – 20:00 UTC). Closed weekends &amp; US holidays.
  </div>
  <div class="meta">
    Market <b>{html.escape(market.upper())}</b> &middot;
    min RVOL <b>{min_rvol:g}×</b> &middot;
    <b id="nflag">{n}</b> stock(s) flagged &middot;
    generated <b id="genstamp">{stamp}</b>
    &middot; click a symbol to open its Yahoo Finance chart &middot; click a column to sort
    <br>{blurb}
  </div>
  <details class="legend" open>
    <summary>What the columns mean</summary>
    <ul>
{legend_html}
    </ul>
  </details>
  <div class="wrap">
  <table id="t">
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Date</th>
        <th class="num">RVOL</th>
        <th class="num">Avg vol</th>
        <th class="num">Day vol</th>
        <th class="num">Prev-day vol</th>
        <th class="num">Avg vol 10d</th>
        <th class="num">Open</th>
        {price_headers}
        {earn_header}
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
  </div>
  <footer>
    Educational tool, not financial advice. {blurb} Built with the
    <span class="ext">volume_scanner</span> project.
  </footer>
<script>
// Shared by the freshness badge and the auto-refresh poller below. genMs is
// mutable: it advances whenever the poller swaps in a newer snapshot.
let genMs = {gen_epoch_ms};
const intraday = {js_intraday};
const dataUrl = {js_data_url};

(function () {{
  const table = document.getElementById('t');
  if (!table) return;
  const tbody = table.tBodies[0];
  table.querySelectorAll('th').forEach((th, idx) => {{
    let asc = true;
    th.addEventListener('click', () => {{
      const rows = Array.from(tbody.rows).filter(r => !r.querySelector('.empty'));
      rows.sort((a, b) => {{
        const x = a.cells[idx].innerText.replace(/[^0-9.\\-]/g, '');
        const y = b.cells[idx].innerText.replace(/[^0-9.\\-]/g, '');
        const nx = parseFloat(x), ny = parseFloat(y);
        let cmp;
        if (!isNaN(nx) && !isNaN(ny)) cmp = nx - ny;
        else cmp = a.cells[idx].innerText.localeCompare(b.cells[idx].innerText);
        return asc ? cmp : -cmp;
      }});
      asc = !asc;
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}})();

// Live "last updated" badge. The age is computed in the viewer's browser from
// the snapshot timestamp — a frozen page (dead token, missed run) visibly
// drifts to amber/red instead of looking identical to a fresh one.
// Show the update time in London and New York (browser handles DST correctly).
function fillTimes() {{
  const ut = document.getElementById('uptimes');
  if (!ut) return;
  const opt = {{ weekday: 'short', day: '2-digit', month: 'short',
                hour: '2-digit', minute: '2-digit' }};
  const lon = new Date(genMs).toLocaleString('en-GB',
                Object.assign({{ timeZone: 'Europe/London' }}, opt));
  const ny = new Date(genMs).toLocaleString('en-US',
                Object.assign({{ timeZone: 'America/New_York' }}, opt));
  ut.textContent = '· ' + lon + ' London · ' + ny + ' New York';
}}
function ago(ms) {{
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return m + ' min ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ' + (m % 60) + 'm ago';
  const d = Math.floor(h / 24);
  return d + 'd ' + (h % 24) + 'h ago';
}}
function marketOpen(now) {{
  const day = now.getUTCDay();                 // 0 Sun .. 6 Sat
  if (day === 0 || day === 6) return false;
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  return mins >= 13 * 60 + 30 && mins <= 20 * 60 + 15;  // ~9:30-16:15 ET
}}
function tick() {{
  const el = document.getElementById('freshness');
  if (!el) return;
  const now = new Date();
  const age = now.getTime() - genMs;
  let cls, label;
  if (intraday) {{
    if (!marketOpen(now)) {{
      cls = 'fresh-idle'; label = 'Market closed · updated ' + ago(age);
    }} else if (age < 40 * 60000) {{
      cls = 'fresh-ok'; label = 'Updated ' + ago(age);
    }} else if (age < 90 * 60000) {{
      cls = 'fresh-warn'; label = 'Updated ' + ago(age) + ' — may be stale';
    }} else {{
      cls = 'fresh-bad'; label = 'Stale · last updated ' + ago(age);
    }}
  }} else {{
    if (age < 30 * 3600000) {{
      cls = 'fresh-ok'; label = 'Updated ' + ago(age);
    }} else if (age < 80 * 3600000) {{
      cls = 'fresh-warn'; label = 'Updated ' + ago(age);
    }} else {{
      cls = 'fresh-bad'; label = 'Stale · last updated ' + ago(age);
    }}
  }}
  el.className = 'freshness ' + cls;
  el.textContent = label;
}}
fillTimes();
tick();
setInterval(tick, 30000);

// Auto-refresh: poll the sibling JSON snapshot and swap the table rows in
// place, so an open tab keeps showing the latest published scan without a
// manual reload. The ?t= cache-buster defeats the Pages CDN per-URL cache.
(function () {{
  if (!dataUrl || !window.fetch) return;
  const tbody = document.querySelector('#t tbody');
  if (!tbody) return;
  async function refresh() {{
    try {{
      const r = await fetch(dataUrl + '?t=' + Date.now(), {{ cache: 'no-store' }});
      if (!r.ok) return;
      const d = await r.json();
      if (!d || !d.rows_html || !(d.generated_ms > genMs)) return;
      tbody.innerHTML = d.rows_html;
      genMs = d.generated_ms;
      const nEl = document.getElementById('nflag');
      if (nEl) nEl.textContent = d.n;
      const st = document.getElementById('genstamp');
      if (st) st.textContent = d.generated;
      fillTimes();
      tick();
    }} catch (e) {{ /* transient network error — try again next interval */ }}
  }}
  setInterval(refresh, 60000);
}})();
</script>
</body>
</html>
"""


def write(df, path: str, **meta) -> str:
    """Write the HTML page plus a sibling .json snapshot the page polls."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    # One timestamp for both files so the page doesn't immediately "update".
    meta.setdefault("generated_at", datetime.now(timezone.utc))
    json_path = os.path.splitext(path)[0] + ".json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(df, data_url=os.path.basename(json_path), **meta))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload(df, **meta), f, ensure_ascii=False)
    return path
