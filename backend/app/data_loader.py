"""Load and normalise NSE CSV files.

Supports:
  * NSE "Get Quote -> Historical Data" downloads (Date, series, OPEN, HIGH, LOW,
    PREV. CLOSE, ltp, close, vwap, 52W H, 52W L, VOLUME, VALUE, No of trades)
    — headers with trailing spaces, numbers with commas, newest-first rows.
  * NSE bhavcopy / security-wise archives (SYMBOL, SERIES, DATE1, OPEN_PRICE,
    HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY ...).
  * Generic OHLCV CSVs (Date/Datetime, Open, High, Low, Close, Volume),
    daily or intraday.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HISTORY_DIR

ALIASES: dict[str, list[str]] = {
    "date": ["date", "date1", "timestamp", "datetime", "trade date", "trading date"],
    "time": ["time"],
    "open": ["open", "open price", "open_price"],
    "high": ["high", "high price", "high_price"],
    "low": ["low", "low price", "low_price"],
    # order matters: prefer the official close over last traded price
    "close": ["close", "close price", "close_price", "closing price", "last price", "last_price", "ltp"],
    "volume": ["volume", "total traded quantity", "ttl_trd_qnty", "tottrdqty", "shares traded",
               "no of shares", "quantity", "qty"],
    "vwap": ["vwap", "avg_price", "average price", "avg price"],
    "symbol": ["symbol", "ticker"],
    "series": ["series"],
}

DATE_FORMATS = [
    "%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M",
]


class DataError(ValueError):
    pass


def _norm(col: str) -> str:
    c = str(col).replace("﻿", "").strip().lower().replace(".", "")
    return re.sub(r"\s+", " ", c)


def _num(s: pd.Series) -> pd.Series:
    if s.dtype.kind in "if":
        return s.astype(float)
    cleaned = s.astype(str).str.replace(",", "", regex=False).str.strip()
    cleaned = cleaned.replace({"-": np.nan, "": np.nan, "nan": np.nan, "None": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def _parse_dates(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    sample = s.dropna().head(50)
    if sample.str.match(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?").mean() > 0.8:
        out = pd.to_datetime(s, errors="coerce", format="ISO8601", utc=False)
        if getattr(out.dt, "tz", None) is not None:
            out = out.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
        return out
    best, best_ok = None, -1
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(sample, format=fmt, errors="coerce")
        ok = parsed.notna().sum()
        if ok > best_ok:
            best, best_ok = fmt, ok
        if ok == len(sample):
            break
    if best_ok > 0:
        return pd.to_datetime(s, format=best, errors="coerce")
    return pd.to_datetime(s, errors="coerce", dayfirst=True)


def guess_symbol(filename: str | None) -> str | None:
    if not filename:
        return None
    m = re.search(r"Quote-Equity-([A-Z0-9&\-]+?)-(EQ|BE|BZ|SM)", filename, re.I)
    if m:
        return m.group(1).upper()
    # NSE index downloads: "NIFTY_50-20-10-2025-to-20-10-2026.csv", "NIFTY BANK-....csv"
    m = re.search(r"([A-Za-z0-9& _]+?)-\d{2}-\d{2}-\d{4}-to-\d{2}-\d{2}-\d{4}", filename)
    if m:
        return re.sub(r"[ _]", "", m.group(1)).upper()
    stem = Path(filename).stem
    token = re.split(r"[_\-\s]+", stem)[0]
    token = re.sub(r"[^A-Za-z0-9&]", "", token).upper()
    return token or None


def load_csv(raw: bytes, filename: str | None = None, symbol: str | None = None) -> tuple[pd.DataFrame, dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    except Exception as e:  # noqa: BLE001
        raise DataError(f"Could not read CSV: {e}") from e
    if df.empty:
        raise DataError("CSV file is empty.")

    norm_cols = {_norm(c): c for c in df.columns}
    mapping: dict[str, str] = {}
    for key, aliases in ALIASES.items():
        for a in aliases:
            if a in norm_cols:
                mapping[key] = norm_cols[a]
                break

    missing = [k for k in ("date", "close") if k not in mapping]
    if missing:
        raise DataError(
            f"Missing required column(s): {missing}. Found columns: {list(df.columns)}. "
            "Expected NSE historical CSV with Date/OPEN/HIGH/LOW/close/VOLUME."
        )

    # Filter to the EQ series if present (NSE files can mix EQ/BE/BL rows)
    if "series" in mapping:
        ser = df[mapping["series"]].astype(str).str.strip().str.upper()
        if (ser == "EQ").any():
            df = df[ser == "EQ"]

    if "symbol" in mapping:
        syms = df[mapping["symbol"]].astype(str).str.strip().str.upper()
        uniq = syms[syms != "NAN"].unique()
        if len(uniq) > 1:
            # multi-stock file (e.g. full-market bhavcopy): keep only the requested symbol
            if not symbol:
                raise DataError(
                    f"This file contains {len(uniq)} stocks (e.g. {', '.join(uniq[:5])}). "
                    "Enter the symbol you want to analyse."
                )
            df = df[syms == symbol.upper().strip()]
            if df.empty:
                raise DataError(f"Symbol {symbol.upper()} not found in this file.")
        elif symbol is None and len(uniq) == 1:
            symbol = uniq[0]
    symbol = (symbol or guess_symbol(filename) or "UNKNOWN").upper().strip()

    date_raw = df[mapping["date"]].astype(str).str.strip()
    if "time" in mapping and mapping["time"] != mapping["date"]:
        date_raw = date_raw + " " + df[mapping["time"]].astype(str).str.strip()
    dates = _parse_dates(date_raw)

    out = pd.DataFrame(index=pd.DatetimeIndex(dates, name="date"))
    out["close"] = _num(df[mapping["close"]]).values
    for k in ("open", "high", "low"):
        out[k] = _num(df[mapping[k]]).values if k in mapping else out["close"]
    out["volume"] = _num(df[mapping["volume"]]).values if "volume" in mapping else 0.0
    if "vwap" in mapping:
        out["vwap_src"] = _num(df[mapping["vwap"]]).values

    out = out[out.index.notna() & out["close"].notna()]
    for k in ("open", "high", "low"):
        out[k] = out[k].fillna(out["close"])
    out["volume"] = out["volume"].fillna(0.0)
    # sanity: high/low must bracket open/close
    out["high"] = out[["high", "open", "close"]].max(axis=1)
    out["low"] = out[["low", "open", "close"]].min(axis=1)

    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.empty:
        raise DataError("No valid price rows found in the file.")
    # Small uploads (e.g. one new day) are fine: they are merged into stored history in main.py.

    deltas = out.index.to_series().diff().dropna()
    intraday = bool(len(deltas) and deltas.median() < pd.Timedelta(hours=20))

    meta = {
        "symbol": symbol,
        "rows_uploaded": int(len(out)),
        "is_intraday": intraday,
        "first_date": out.index[0].isoformat(),
        "last_date": out.index[-1].isoformat(),
        "columns_mapped": mapping,
    }
    return out[["open", "high", "low", "close", "volume"] + (["vwap_src"] if "vwap_src" in out else [])], meta


def _history_path(symbol: str, intraday: bool) -> Path:
    return HISTORY_DIR / f"{re.sub(r'[^A-Z0-9&_-]', '_', symbol)}_{'intraday' if intraday else 'daily'}.csv"


def history_is_intraday(symbol: str) -> bool:
    """For tiny uploads: daily unless only an intraday history exists for this symbol."""
    return not _history_path(symbol, False).exists() and _history_path(symbol, True).exists()


def merge_history(df: pd.DataFrame, symbol: str, intraday: bool) -> tuple[pd.DataFrame, int]:
    """Merge the upload into the stored history for this symbol so the training set grows over time."""
    path = _history_path(symbol, intraday)
    if path.exists():
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        old.index.name = "date"
        combined = pd.concat([old, df])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = df
    combined.to_csv(path)
    return combined, int(len(combined))
