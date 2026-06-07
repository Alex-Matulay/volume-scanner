"""Streamlit dashboard for the unusual-volume scanner.

Run from the repo root:
  streamlit run volume_scanner/dashboard.py
"""

from __future__ import annotations

import os
import sys

# Allow `streamlit run volume_scanner/dashboard.py` to import the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
import yfinance as yf

from volume_scanner import universe
from volume_scanner.scanner import ScanConfig, scan

st.set_page_config(page_title="Volume Scanner", layout="wide")
st.title("📈 Unusual Volume Scanner — US / UK / EU")
st.caption(
    "End-of-day relative-volume (RVOL) scanner. Flags stocks trading well above "
    "their normal volume. Educational tool — not financial advice."
)

with st.sidebar:
    st.header("Scan settings")
    market = st.selectbox("Market", ["us", "uk", "eu", "all"], index=0)
    min_rvol = st.slider("Min relative volume (RVOL)", 1.0, 20.0, 3.0, 0.5)
    lookback = st.slider("Baseline length (days)", 5, 60, 20)
    min_dollar_vol = st.select_slider(
        "Min dollar volume",
        options=[1e5, 5e5, 1e6, 5e6, 1e7, 5e7, 1e8],
        value=1e6,
        format_func=lambda v: f"${v:,.0f}",
    )
    limit = st.number_input(
        "Cap universe size (0 = no cap)", min_value=0, value=500, step=100,
        help="Scanning the full US list takes several minutes. Cap it for quick runs.",
    )
    run = st.button("Run scan", type="primary")

if "results" not in st.session_state:
    st.session_state.results = None


@st.cache_data(show_spinner=False, ttl=1800)
def _universe(market: str) -> list[str]:
    return universe.build_universe(market)


def _run_scan(market, min_rvol, lookback, min_dollar_vol, limit):
    tickers = _universe(market)
    if limit and limit > 0:
        tickers = tickers[:limit]
    cfg = ScanConfig(
        lookback_days=lookback, min_rvol=min_rvol, min_dollar_vol=min_dollar_vol
    )
    bar = st.progress(0.0, text=f"Scanning {len(tickers):,} tickers...")

    def progress(done, total):
        bar.progress(min(done / total, 1.0), text=f"Scanned {done:,}/{total:,}")

    df = scan(tickers, cfg, progress=progress)
    bar.empty()
    return df


if run:
    with st.spinner("Downloading and scanning..."):
        st.session_state.results = _run_scan(
            market, min_rvol, lookback, min_dollar_vol, int(limit)
        )

df = st.session_state.results

if df is None:
    st.info("Set your filters on the left and press **Run scan**.")
elif df.empty:
    st.warning("No stocks matched the filters. Try lowering Min RVOL.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matches", f"{len(df):,}")
    c2.metric("Top RVOL", f"{df['rvol'].max():.1f}×")
    c3.metric("Gainers", int((df["direction"] == "up").sum()))
    c4.metric("Decliners", int((df["direction"] == "down").sum()))

    st.subheader("Results (ranked by RVOL)")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "rvol": st.column_config.NumberColumn("RVOL", format="%.2f×"),
            "pct_change": st.column_config.NumberColumn("% chg", format="%.2f%%"),
            "avg_volume": st.column_config.NumberColumn("Avg vol", format="%d"),
            "last_volume": st.column_config.NumberColumn("Day vol", format="%d"),
            "prev_volume": st.column_config.NumberColumn("Prev-day vol", format="%d"),
            "avg_volume_10d": st.column_config.NumberColumn("Avg vol 10d", format="%d"),
            "open": st.column_config.NumberColumn("Open", format="%.2f"),
            "close": st.column_config.NumberColumn("Close", format="%.2f"),
            "dollar_vol": st.column_config.NumberColumn("$ vol", format="$%d"),
        },
    )

    st.download_button(
        "Download CSV", df.to_csv(index=False).encode(),
        file_name="volume_scan.csv", mime="text/csv",
    )

    st.subheader("Inspect a ticker")
    pick = st.selectbox("Symbol", df["symbol"].tolist())
    if pick:
        hist = yf.download(pick, period="6mo", interval="1d",
                           auto_adjust=False, progress=False)
        if not hist.empty:
            colp, colv = st.columns(2)
            colp.line_chart(hist["Close"], height=260)
            colp.caption(f"{pick} — close (6mo)")
            colv.bar_chart(hist["Volume"], height=260)
            colv.caption(f"{pick} — volume (6mo)")
