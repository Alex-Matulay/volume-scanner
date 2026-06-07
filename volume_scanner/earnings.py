"""Earnings tracker: flag flagged stocks that just posted record quarterly results.

For each symbol we pull, from yfinance (free):
  * the quarterly income statement (~5 recent quarters) -> revenue / net income / EPS
  * the earnings calendar -> last reported date and the EPS surprise %

From that we derive, per stock:
  earnings_date   last reported earnings date
  near_spike      earnings reported within a few days of the scan date (the
                  likely catalyst for the volume spike)
  eps_surprise    reported EPS vs. estimate, in %
  rev_yoy         latest quarter revenue vs. the same quarter a year earlier, in %
  record_quarter  latest quarter revenue is the highest in the available history
  earnings_note   short human-readable summary

Caveat: yfinance only exposes ~5 quarters, so "record" means "highest of the
available quarters", not necessarily an all-time record. The note says so.
"""

from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
import yfinance as yf

# Columns this module adds to a results DataFrame.
EARNINGS_COLS = [
    "earnings_date", "near_spike", "eps_surprise", "rev_yoy",
    "record_quarter", "earnings_note",
]


def _first_row(df: pd.DataFrame, names: list[str]) -> pd.Series | None:
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def _as_date(x) -> date | None:
    try:
        return pd.Timestamp(x).date()
    except Exception:
        return None


def fetch_earnings(symbol: str, as_of: date | None = None) -> dict:
    """Return earnings metrics for one symbol (best-effort; never raises)."""
    out = {c: None for c in EARNINGS_COLS}
    out["near_spike"] = False
    out["record_quarter"] = False
    out["earnings_note"] = ""
    try:
        t = yf.Ticker(symbol)

        # --- Quarterly revenue / EPS (record + YoY) -------------------------
        rev_record = False
        rev_yoy = None
        rev_high_note = ""
        try:
            q = t.quarterly_income_stmt
            if q is not None and not q.empty:
                q = q.reindex(sorted(q.columns, reverse=True), axis=1)  # newest first
                rev = _first_row(q, ["Total Revenue", "TotalRevenue", "Operating Revenue"])
                if rev is not None:
                    rev = rev.dropna().astype(float)
                    if len(rev) >= 4:
                        latest = float(rev.iloc[0])
                        if latest > 0 and latest >= float(rev.max()):
                            rev_record = True
                            rev_high_note = f"record revenue ({len(rev)}q high)"
                        if len(rev) >= 5 and float(rev.iloc[4]) > 0:
                            rev_yoy = (latest / float(rev.iloc[4]) - 1.0) * 100.0
        except Exception:
            pass
        out["record_quarter"] = bool(rev_record)
        out["rev_yoy"] = round(rev_yoy, 1) if rev_yoy is not None else None

        # --- Last reported earnings date + surprise -------------------------
        e_date = None
        surprise = None
        try:
            ed = t.get_earnings_dates(limit=12)
            if ed is not None and not ed.empty and "Reported EPS" in ed.columns:
                ed = ed.sort_index(ascending=False)
                reported = ed[ed["Reported EPS"].notna()]
                if not reported.empty:
                    row = reported.iloc[0]
                    e_date = _as_date(reported.index[0])
                    s = row.get("Surprise(%)")
                    surprise = float(s) if pd.notna(s) else None
        except Exception:
            pass
        out["earnings_date"] = e_date.isoformat() if e_date else None
        out["eps_surprise"] = round(surprise, 1) if surprise is not None else None

        # --- Was the spike right after earnings? ----------------------------
        ref = as_of or date.today()
        if e_date is not None:
            gap = (ref - e_date).days
            out["near_spike"] = bool(0 <= gap <= 4)

        # --- Build the note -------------------------------------------------
        bits = []
        if rev_high_note:
            bits.append(rev_high_note)
        if rev_yoy is not None:
            bits.append(f"{rev_yoy:+.0f}% YoY rev")
        if e_date is not None:
            if out["near_spike"]:
                gap = (ref - e_date).days
                when = "same day" if gap == 0 else f"{gap}d before spike"
                bits.append(f"reported {e_date.isoformat()} ({when})")
            else:
                bits.append(f"last earnings {e_date.isoformat()}")
        if surprise is not None:
            verb = "beat" if surprise >= 0 else "miss"
            bits.append(f"EPS {verb} {surprise:+.1f}%")
        out["earnings_note"] = "; ".join(bits)
    except Exception:
        pass
    return out


def annotate(df: pd.DataFrame, *, as_of: date | None = None,
             pause: float = 0.0, progress=None) -> pd.DataFrame:
    """Add EARNINGS_COLS to a results DataFrame (one yfinance lookup per row)."""
    if df is None or df.empty:
        for c in EARNINGS_COLS:
            df[c] = None
        return df

    # If the scan rows carry a date, use the most common one as the spike date.
    if as_of is None and "date" in df.columns:
        try:
            as_of = _as_date(str(df["date"].iloc[0]).split()[0])
        except Exception:
            as_of = None

    records = []
    total = len(df)
    for i, sym in enumerate(df["symbol"].tolist(), 1):
        records.append(fetch_earnings(str(sym), as_of=as_of))
        if progress:
            progress(i, total)
        if pause:
            time.sleep(pause)

    add = pd.DataFrame(records, index=df.index)
    for c in EARNINGS_COLS:
        df[c] = add[c]
    return df
