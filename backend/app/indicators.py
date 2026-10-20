"""Technical indicators implemented with pandas/numpy (no TA-Lib dependency)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    avg_gain = wilder(delta.clip(lower=0), n)
    avg_loss = wilder(-delta.clip(upper=0), n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(avg_loss != 0, 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * std, mid - k * std
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    width = (upper - lower) / mid
    return mid, upper, lower, pct_b, width


def stochastic(df: pd.DataFrame, n=14, smooth=3):
    ll = df["low"].rolling(n, min_periods=n).min()
    hh = df["high"].rolling(n, min_periods=n).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    k = raw.rolling(smooth).mean()
    d = k.rolling(smooth).mean()
    return k, d


def adx(df: pd.DataFrame, n=14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_ = wilder(true_range(df), n)
    plus_di = 100 * wilder(plus_dm, n) / atr_
    minus_di = 100 * wilder(minus_dm, n) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder(dx, n), plus_di, minus_di


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def supertrend(df: pd.DataFrame, period=10, mult=3.0):
    hl2 = (df["high"] + df["low"]) / 2
    atr_ = atr(df, period)
    fu = (hl2 + mult * atr_).to_numpy(copy=True)
    fl = (hl2 - mult * atr_).to_numpy(copy=True)
    c = df["close"].to_numpy()
    n = len(df)
    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(fu[i]):
            continue
        if i == 0 or np.isnan(fu[i - 1]):
            direction[i], st[i] = 1, fl[i]
            continue
        if not (fu[i] < fu[i - 1] or c[i - 1] > fu[i - 1]):
            fu[i] = fu[i - 1]
        if not (fl[i] > fl[i - 1] or c[i - 1] < fl[i - 1]):
            fl[i] = fl[i - 1]
        if direction[i - 1] == 1:
            direction[i] = -1 if c[i] < fl[i] else 1
        else:
            direction[i] = 1 if c[i] > fu[i] else -1
        st[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def vwap(df: pd.DataFrame, intraday: bool) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    if intraday:
        day = df.index.normalize()
        return pv.groupby(day).cumsum() / df["volume"].groupby(day).cumsum().replace(0, np.nan)
    if "vwap_src" in df and df["vwap_src"].notna().mean() > 0.8:
        # NSE daily vwap is per-session; a 20-day volume-weighted average is more useful for swing context
        pv = df["vwap_src"] * df["volume"]
    return pv.rolling(20).sum() / df["volume"].rolling(20).sum().replace(0, np.nan)


def add_all(df: pd.DataFrame, intraday: bool = False) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    for n in (20, 50, 100, 200):
        df[f"sma{n}"] = sma(c, n)
    for n in (9, 21, 50):
        df[f"ema{n}"] = ema(c, n)
    df["rsi"] = rsi(c)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(c)
    df["bb_mid"], df["bb_upper"], df["bb_lower"], df["bb_pctb"], df["bb_width"] = bollinger(c)
    df["atr"] = atr(df)
    df["stoch_k"], df["stoch_d"] = stochastic(df)
    df["adx"], df["plus_di"], df["minus_di"] = adx(df)
    df["obv"] = obv(df)
    df["supertrend"], df["st_dir"] = supertrend(df)
    df["vwap"] = vwap(df, intraday)
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    from .patterns import detect, pattern_columns  # local import avoids a cycle
    pc = pattern_columns(detect(df))
    df["pat_bull"], df["pat_bear"] = pc["pat_bull"], pc["pat_bear"]
    return df


# ---------------------------------------------------------------- levels

def pivot_points(h: float, l: float, c: float) -> dict:
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    tc, bc = max(tc, bc), min(tc, bc)
    return {
        "P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l),
        "R3": h + 2 * (p - l), "S3": l - 2 * (h - p), "TC": tc, "BC": bc,
    }


def session_bars(df: pd.DataFrame, intraday: bool) -> pd.DataFrame:
    """Daily OHLC bars (resampled when the upload is intraday)."""
    if not intraday:
        return df
    return df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                  "volume": "sum"}).dropna(subset=["close"])


def swing_levels(df: pd.DataFrame, window=5, lookback=250, max_levels=4) -> dict:
    d = df.tail(lookback)
    span = 2 * window + 1
    hi = d["high"][d["high"] == d["high"].rolling(span, center=True).max()]
    lo = d["low"][d["low"] == d["low"].rolling(span, center=True).min()]
    pts = sorted(list(hi.values) + list(lo.values))
    clusters: list[list[float]] = []
    for p in pts:
        if clusters and abs(p - np.mean(clusters[-1])) / p < 0.015:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [{"price": float(np.mean(cl)), "touches": len(cl)} for cl in clusters]
    price = float(df["close"].iloc[-1])
    res = sorted([lv for lv in levels if lv["price"] > price * 1.002], key=lambda x: x["price"])[:max_levels]
    sup = sorted([lv for lv in levels if lv["price"] < price * 0.998], key=lambda x: -x["price"])[:max_levels]
    return {"supports": sup, "resistances": res}


def candle_patterns(df: pd.DataFrame) -> list[dict]:
    """Patterns on the latest candle (full detector lives in patterns.py)."""
    from .patterns import latest_patterns
    return latest_patterns(df) if len(df) >= 3 else []
