"""Render scan results as a self-contained static HTML page.

The page has no external dependencies (inline CSS + a little vanilla JS for
click-to-sort), so it can be served as-is by GitHub Pages. Every symbol links
to its Yahoo Finance quote/chart page so you can open a chart in one click.
"""

from __future__ import annotations

import html
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


def render(df, *, market: str = "us", min_rvol: float = 3.0,
           generated_at: datetime | None = None) -> str:
    """Return a full HTML document string for the given results DataFrame."""
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    n = 0 if df is None else len(df)

    has_earn = df is not None and "earnings_note" in df.columns
    n_cols = (12 if has_earn else 11) + 4  # +4 volatility / flow columns

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
            note = html.escape(str(r.get("notes", "") or ""))

            # Volatility (day's range) + buy/sell flow.
            rng = _fmt_num(r.get("day_range_pct"), 1)
            rng_str = "-" if rng == "-" else rng + "%"
            volx = _fmt_num(r.get("range_vs_avg"), 1)
            volx_str = "-" if volx == "-" else volx + "×"
            buy = _fmt_num(r.get("buy_vol_pct"), 0)
            buy_str = "-" if buy == "-" else buy + "%"
            flow_txt = str(r.get("flow", "") or "")
            fcls = {"bought up": "flow-buy", "sold off": "flow-sell"}.get(flow_txt, "flow-mix")
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
                f'<td class="num">{_fmt_num(r.get("close"))}</td>'
                f'<td class="num {cls}">{pct_str}</td>'
                f'<td class="num">{rng_str}</td>'
                f'<td class="num">{volx_str}</td>'
                f'<td class="num">{buy_str}</td>'
                f'<td class="{fcls}">{html.escape(flow_txt)}</td>'
                f'<td class="note">{note}</td>'
                f'{earn_cell}'
                "</tr>"
            )
    body_rows = "\n".join(rows_html) or (
        f'<tr><td colspan="{n_cols}" class="empty">No stocks matched the filters '
        "for this run.</td></tr>"
    )
    earn_header = "<th>Earnings</th>" if has_earn else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unusual Volume Scanner</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 1.5rem; background: #0f1115; color: #e6e6e6; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.4rem; }}
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
  .note {{ color: #8b94a3; font-size: .8rem; }}
  .flow-buy {{ color: #4ade80; font-weight: 600; }}
  .flow-sell {{ color: #f87171; font-weight: 600; }}
  .flow-mix {{ color: #9aa4b2; }}
  .earn {{ color: #b6c0cf; font-size: .8rem; white-space: normal; min-width: 22rem; }}
  .earn.record {{ color: #ffd479; font-weight: 600; }}
  .earn.near {{ color: #7dd3fc; }}
  .empty {{ text-align: center; color: #9aa4b2; padding: 2rem; }}
  footer {{ margin-top: 1rem; color: #6b7280; font-size: .78rem; }}
  a.ext {{ color: #6ea8fe; }}
</style>
</head>
<body>
  <h1>\U0001F4C8 Unusual Volume Scanner</h1>
  <div class="meta">
    Market <b>{html.escape(market.upper())}</b> &middot;
    min RVOL <b>{min_rvol:g}×</b> &middot;
    <b>{n}</b> stock(s) flagged &middot;
    generated <b>{stamp}</b>
    &middot; click a symbol to open its Yahoo Finance chart &middot; click a column to sort
  </div>
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
        <th class="num">Close</th>
        <th class="num">% chg</th>
        <th class="num">Range</th>
        <th class="num">Vol vs avg</th>
        <th class="num">Buy vol</th>
        <th>Flow</th>
        <th>Notes</th>
        {earn_header}
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
  </div>
  <footer>
    Educational tool, not financial advice. Volume is end-of-day; figures tagged
    "consolidated" match Yahoo / brokers. Built with the
    <span class="ext">volume_scanner</span> project.
  </footer>
<script>
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
</script>
</body>
</html>
"""


def write(df, path: str, **meta) -> str:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(df, **meta))
    return path
