"""Build the ticker universe to scan.

US tickers are fetched live from the public NASDAQ Trader symbol directory
(NASDAQ + NYSE/AMEX), which is the cleanest free full list available.

UK + EU coverage uses curated large-cap constituents (FTSE 100, DAX, CAC 40,
AEX, IBEX, FTSE MIB, plus a few more) with the Yahoo Finance exchange suffixes
that yfinance understands (.L London, .DE Xetra, .PA Paris, .AS Amsterdam,
.MC Madrid, .MI Milan, .BR Brussels, .LS Lisbon, .HE Helsinki, .ST Stockholm,
.OL Oslo, .CO Copenhagen, .IR Dublin, .VI Vienna).

There is no public, complete list of every Trading212 instrument, so this is a
practical superset of the most-traded names rather than a literal T212 mirror.
You can always pass your own list via a CSV with a "symbol" column.
"""

from __future__ import annotations

import io
import os

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def _fetch_pipe_file(url: str) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), sep="|")
    # The last row is a "File Creation Time" footer.
    return df[~df.iloc[:, 0].astype(str).str.startswith("File Creation Time")]


def fetch_us(include_etfs: bool = False) -> list[str]:
    """Full US common-stock universe from NASDAQ Trader (cached to data/)."""
    cache = os.path.join(CACHE_DIR, "us_symbols.csv")
    if os.path.exists(cache):
        return pd.read_csv(cache)["symbol"].tolist()

    symbols: list[str] = []

    nq = _fetch_pipe_file(NASDAQ_LISTED)
    nq = nq[nq["Test Issue"] == "N"]
    if not include_etfs and "ETF" in nq.columns:
        nq = nq[nq["ETF"] != "Y"]
    symbols += nq["Symbol"].dropna().astype(str).tolist()

    other = _fetch_pipe_file(OTHER_LISTED)
    other = other[other["Test Issue"] == "N"]
    if not include_etfs and "ETF" in other.columns:
        other = other[other["ETF"] != "Y"]
    # Use NASDAQ Symbol col where present, else ACT Symbol.
    col = "NASDAQ Symbol" if "NASDAQ Symbol" in other.columns else "ACT Symbol"
    symbols += other[col].dropna().astype(str).tolist()

    # Yahoo uses '-' for share-class dots (e.g. BRK.B -> BRK-B) and rejects '$'.
    clean = sorted(
        {s.replace(".", "-").strip() for s in symbols if s and "$" not in s}
    )
    os.makedirs(CACHE_DIR, exist_ok=True)
    pd.DataFrame({"symbol": clean}).to_csv(cache, index=False)
    return clean


# --- Curated UK + EU large caps (Yahoo suffixes) -------------------------------

FTSE_100 = [
    "AAL", "ABF", "ADM", "AHT", "ANTO", "AUTO", "AV", "AZN", "BA", "BARC",
    "BATS", "BDEV", "BEZ", "BKG", "BME", "BNZL", "BP", "BRBY", "BT-A", "CCH",
    "CNA", "CPG", "CRDA", "CTEC", "DCC", "DGE", "DPLM", "EDV", "ENT", "EXPN",
    "FCIT", "FRES", "GLEN", "GSK", "HIK", "HLMA", "HLN", "HSBA", "HWDN", "IAG",
    "IHG", "III", "IMB", "IMI", "INF", "ITRK", "JD", "KGF", "LAND", "LGEN",
    "LLOY", "LMP", "LSEG", "MKS", "MNDI", "MNG", "MRO", "NG", "NWG", "NXT",
    "PHNX", "PRU", "PSH", "PSN", "PSON", "REL", "RIO", "RKT", "RMV", "RR",
    "RTO", "SBRY", "SDR", "SGE", "SGRO", "SHEL", "SMDS", "SMIN", "SMT", "SN",
    "SPX", "SSE", "STAN", "STJ", "SVT", "TSCO", "TW", "ULVR", "UTG", "UU",
    "VOD", "WEIR", "WPP", "WTB",
]

DAX_40 = [
    "ADS", "AIR", "ALV", "BAS", "BAYN", "BEI", "BMW", "BNR", "CBK", "CON",
    "1COV", "DBK", "DB1", "DHL", "DTE", "DTG", "ENR", "EOAN", "FME", "FRE",
    "HEI", "HEN3", "HNR1", "IFX", "MBG", "MRK", "MTX", "MUV2", "P911", "PAH3",
    "QIA", "RHM", "RWE", "SAP", "SHL", "SIE", "SRT3", "SY1", "VOW3", "ZAL",
]

CAC_40 = [
    "AC", "ACA", "AI", "AIR", "BN", "BNP", "CA", "CAP", "CS", "DG",
    "DSY", "EN", "ENGI", "EL", "ERF", "GLE", "HO", "KER", "LR", "MC",
    "ML", "OR", "ORA", "PUB", "RI", "RMS", "RNO", "SAF", "SAN", "SGO",
    "SU", "SW", "TEP", "TTE", "VIE", "VIV", "WLN",
]

AEX = [
    "ADYEN", "AD", "AGN", "AKZA", "ASML", "ASM", "ASRNL", "BESI", "DSFIR",
    "GLPG", "HEIA", "IMCD", "INGA", "KPN", "MT", "NN", "PHIA", "PRX", "RAND",
    "REN", "SHELL", "UMG", "WKL",
]

IBEX = [
    "ACS", "AENA", "AMS", "ANA", "BBVA", "BKT", "CABK", "CLNX", "ELE", "ENG",
    "FER", "GRF", "IAG", "IBE", "ITX", "MAP", "MEL", "MTS", "NTGY", "RED",
    "REP", "SAB", "SAN", "SCYR", "TEF",
]

FTSE_MIB = [
    "A2A", "AMP", "AZM", "BAMI", "BMED", "BMPS", "BPE", "CPR", "DIA", "ENEL",
    "ENI", "ERG", "FBK", "G", "HER", "INW", "IP", "ISP", "LDO", "MB",
    "MONC", "NEXI", "PIRC", "PST", "PRY", "RACE", "REC", "SPM", "SRG", "STLAM",
    "STMMI", "TEN", "TIT", "TRN", "UCG", "UNI",
]

# Each block maps to its Yahoo Finance suffix.
_EU_BLOCKS = {
    ".L": FTSE_100,
    ".DE": DAX_40,
    ".PA": CAC_40,
    ".AS": AEX,
    ".MC": IBEX,
    ".MI": FTSE_MIB,
}


def fetch_uk_eu() -> list[str]:
    out: list[str] = []
    for suffix, names in _EU_BLOCKS.items():
        out += [f"{n}{suffix}" for n in names]
    return sorted(set(out))


def fetch_uk() -> list[str]:
    return sorted({f"{n}.L" for n in FTSE_100})


def build_universe(market: str = "all", include_etfs: bool = False) -> list[str]:
    """market: 'us', 'uk', 'eu', or 'all'."""
    market = market.lower()
    tickers: list[str] = []
    if market in ("us", "all"):
        tickers += fetch_us(include_etfs=include_etfs)
    if market in ("uk", "all"):
        tickers += fetch_uk()
    if market in ("eu", "all"):
        # eu block includes UK in 'all'; for 'eu' alone include continental only.
        if market == "eu":
            for suffix, names in _EU_BLOCKS.items():
                if suffix == ".L":
                    continue
                tickers += [f"{n}{suffix}" for n in names]
        else:
            tickers += fetch_uk_eu()
    return sorted(set(tickers))


def load_csv(path: str) -> list[str]:
    df = pd.read_csv(path)
    col = "symbol" if "symbol" in df.columns else df.columns[0]
    return sorted(set(df[col].dropna().astype(str).tolist()))
