"""Download and parse NSE end-of-day bhavcopy files.

Sources (all public, published by NSE every trading day around 6 pm IST):
  * Equity, UDiFF format (current, since July 2024):
      https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  * Equity, "full" security-wise file (fallback, also has delivery %):
      https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  * Indices (NIFTY 50, NIFTY BANK, ...):
      https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv

Every downloaded file is cached under data/bhavcopy/, so a 1-year backfill is
fetched once and reused for every symbol you add later. A 404 means the market
was closed that day (holiday) or the file isn't published yet.
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd
import requests

from .config import BHAV_DIR

log = logging.getLogger(__name__)

BASE = "https://nsearchives.nseindia.com"
URLS = {
    "eq_udiff": BASE + "/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    "eq_full": BASE + "/products/content/sec_bhavdata_full_{dmy}.csv",
    "index": BASE + "/content/indices/ind_close_all_{dmy}.csv",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "text/csv,application/zip,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
}
SERIES_PREF = ["EQ", "BE", "BZ", "SM", "ST"]
INDEX_HINT = re.compile(r"^(NIFTY|INDIAVIX|NIFTYBANK|BANKNIFTY|FINNIFTY)")


class BhavcopyError(RuntimeError):
    pass


def norm_symbol(s: str) -> str:
    """'Nifty 50' -> 'NIFTY50', 'm&m' -> 'M&M', 'bajaj-auto' -> 'BAJAJ-AUTO' (matches CSV-upload symbols)."""
    return re.sub(r"[^A-Z0-9&-]", "", str(s).upper())


def guess_kind(symbol: str) -> str:
    return "index" if INDEX_HINT.match(norm_symbol(symbol)) else "equity"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip()
                         .replace({"-": np.nan, "": np.nan, "nan": np.nan}), errors="coerce")


# ------------------------------------------------------------------ parsers

def parse_equity_udiff(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(z.open(name), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if "FinInstrmTp" in df:
        df = df[df["FinInstrmTp"].str.strip().str.upper().isin(["STK", "ETF"])] if df["FinInstrmTp"].notna().any() else df
    out = pd.DataFrame({
        "symbol": df["TckrSymb"].str.strip().str.upper(),
        "series": df["SctySrs"].str.strip().str.upper(),
        "date": pd.to_datetime(df["TradDt"].str.strip(), errors="coerce"),
        "open": _num(df["OpnPric"]), "high": _num(df["HghPric"]), "low": _num(df["LwPric"]),
        "close": _num(df["ClsPric"]), "volume": _num(df["TtlTradgVol"]),
    })
    turnover = _num(df["TtlTrfVal"]) if "TtlTrfVal" in df else np.nan
    out["vwap_src"] = turnover / out["volume"].replace(0, np.nan)
    # extra columns used by the market briefing (breadth, top movers); ignored by per-symbol history
    out["prev_close"] = _num(df["PrvsClsgPric"]) if "PrvsClsgPric" in df else np.nan
    out["turnover"] = turnover  # rupees
    return out.dropna(subset=["date", "close"])


def parse_equity_full(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    df.columns = [c.strip().upper() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].str.upper(), "series": df["SERIES"].str.upper(),
        "date": pd.to_datetime(df["DATE1"], format="%d-%b-%Y", errors="coerce"),
        "open": _num(df["OPEN_PRICE"]), "high": _num(df["HIGH_PRICE"]), "low": _num(df["LOW_PRICE"]),
        "close": _num(df["CLOSE_PRICE"]), "volume": _num(df["TTL_TRD_QNTY"]),
        "vwap_src": _num(df["AVG_PRICE"]) if "AVG_PRICE" in df else np.nan,
        "prev_close": _num(df["PREV_CLOSE"]) if "PREV_CLOSE" in df else np.nan,
        "turnover": _num(df["TURNOVER_LACS"]) * 1e5 if "TURNOVER_LACS" in df else np.nan,
    })
    return out.dropna(subset=["date", "close"])


def parse_index(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), dtype=str)
    cols = {c.strip().lower(): c for c in df.columns}

    def col(*keys):
        for k, orig in cols.items():
            if all(x in k for x in keys):
                return df[orig]
        return pd.Series(np.nan, index=df.index)

    close = _num(col("clos"))
    out = pd.DataFrame({
        "symbol": col("index name").map(norm_symbol),
        "name": col("index name").str.strip(),
        "series": "IDX",
        "date": pd.to_datetime(col("index date").str.strip(), dayfirst=True, errors="coerce"),
        "open": _num(col("open")), "high": _num(col("high")), "low": _num(col("low")),
        "close": close, "volume": _num(col("volume")),
        "pct_change": _num(col("change(%)")), "pe": _num(col("p/e")),
    })
    for k in ("open", "high", "low"):
        out[k] = out[k].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0)
    return out.dropna(subset=["date", "close"])


PARSERS = {"eq_udiff": parse_equity_udiff, "eq_full": parse_equity_full, "index": parse_index}


# ------------------------------------------------------------------ client

class BhavcopyClient:
    def __init__(self, fetcher: Callable[[str], bytes | None] | None = None, pause: float = 0.35):
        self.fetcher = fetcher  # test hook: url -> bytes, or None for "not published"
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._warmed = False
        self.downloads = 0
        self.mismatched: list = []

    # -- network
    def _warmup(self):
        """Some NSE endpoints want the cookies set by the main site first."""
        try:
            self.session.get("https://www.nseindia.com/", timeout=20)
        except requests.RequestException:
            pass
        self._warmed = True

    def _get(self, url: str) -> bytes | None:
        if self.fetcher:
            return self.fetcher(url)
        last = None
        for attempt in range(4):
            try:
                r = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200 and r.content:
                head = r.content[:300].lower()
                if b"<html" in head or b"<!doctype" in head:  # NSE error pages come back as HTML 200s
                    return None
                return r.content
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403) and not self._warmed:
                self._warmup()
                continue
            last = f"HTTP {r.status_code}"
            time.sleep(1.5 * (attempt + 1))
        raise BhavcopyError(f"Download failed for {url}: {last}")

    # -- cache
    def _fetch(self, kind: str, d: date) -> bytes | None:
        url = URLS[kind].format(ymd=d.strftime("%Y%m%d"), dmy=d.strftime("%d%m%Y"))
        fname = url.rsplit("/", 1)[1]
        folder = BHAV_DIR / str(d.year)
        folder.mkdir(parents=True, exist_ok=True)
        path, missing = folder / fname, folder / (fname + ".missing")
        if path.exists():
            return path.read_bytes()
        if missing.exists():
            return None
        raw = self._get(url)
        self.downloads += 1
        if self.pause and not self.fetcher:
            time.sleep(self.pause)  # be polite to NSE's servers
        if raw is None:
            # remember holidays, but keep retrying recent days (file may be published later)
            if (date.today() - d).days > 3:
                missing.touch()
            return None
        path.write_bytes(raw)
        return raw

    def _checked(self, kind: str, d: date, raw: bytes) -> pd.DataFrame | None:
        """Parse a file and make sure it really is for day `d`. NSE occasionally serves a
        previous session's content under a new date; caching that would corrupt history."""
        df = PARSERS[kind](raw)
        dates = set(df["date"].dt.date.dropna().unique())
        if dates and dates != {d}:
            log.warning("%s file for %s contains trade date(s) %s — ignoring it", kind, d, sorted(dates)[:3])
            self._discard(kind, d)
            self.mismatched.append((kind, d.isoformat(), sorted(str(x) for x in dates)[:3]))
            return None
        return df

    def _discard(self, kind: str, d: date):
        url = URLS[kind].format(ymd=d.strftime("%Y%m%d"), dmy=d.strftime("%d%m%Y"))
        (BHAV_DIR / str(d.year) / url.rsplit("/", 1)[1]).unlink(missing_ok=True)

    def equity_day(self, d: date) -> pd.DataFrame | None:
        for kind in ("eq_udiff", "eq_full"):
            try:
                raw = self._fetch(kind, d)
                if raw is not None:
                    df = self._checked(kind, d, raw)
                    if df is not None:
                        return df
            except BhavcopyError:
                raise
            except Exception as e:  # noqa: BLE001  corrupt/changed file: try the other source
                log.warning("could not parse %s for %s: %s", kind, d, e)
                self._discard(kind, d)
        return None

    def index_day(self, d: date) -> pd.DataFrame | None:
        raw = self._fetch("index", d)
        if raw is None:
            return None
        try:
            return self._checked("index", d, raw)
        except Exception as e:  # noqa: BLE001
            log.warning("could not parse index file for %s: %s", d, e)
            self._discard("index", d)
            return None


def pick_rows(day_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Rows for one symbol from a full-market day file (best series first)."""
    s = norm_symbol(symbol)
    rows = day_df[day_df["symbol"].map(norm_symbol) == s]
    if rows.empty:
        return rows
    for ser in SERIES_PREF + ["IDX"]:
        hit = rows[rows["series"] == ser]
        if not hit.empty:
            return hit.iloc[[0]]
    return rows.iloc[[0]]


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)
