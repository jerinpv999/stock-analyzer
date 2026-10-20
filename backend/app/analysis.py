"""Rule-based technical analysis for three timeframes + trade plans."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .indicators import candle_patterns, pivot_points, session_bars, swing_levels


def _v(row: pd.Series, key: str):
    v = row.get(key)
    if v is None or pd.isna(v):
        return None
    return float(v)


def _sig(name, value, bias, note):
    return {"indicator": name, "value": None if value is None else round(float(value), 2),
            "bias": int(bias), "note": note}


def _score(signals: list[dict]) -> float:
    if not signals:
        return 0.0
    return 100.0 * sum(s["bias"] for s in signals) / len(signals)


def verdict(score: float) -> str:
    if score >= 60:
        return "Strong Bullish"
    if score >= 25:
        return "Bullish"
    if score <= -60:
        return "Strong Bearish"
    if score <= -25:
        return "Bearish"
    return "Neutral"


def _rr(entry, sl, target):
    risk = abs(entry - sl)
    return round(abs(target - entry) / risk, 2) if risk > 0 else None


# ------------------------------------------------------------------ levels

def compute_levels(df: pd.DataFrame, intraday: bool) -> dict:
    daily = session_bars(df, intraday)
    last = daily.iloc[-1]
    prev = daily.iloc[-2] if len(daily) > 1 else last
    piv = pivot_points(last["high"], last["low"], last["close"])
    prev_piv = pivot_points(prev["high"], prev["low"], prev["close"])
    swings = swing_levels(df if not intraday else daily)
    hi52 = float(daily["high"].tail(252).max())
    lo52 = float(daily["low"].tail(252).min())
    cpr_width_pct = (piv["TC"] - piv["BC"]) / piv["P"] * 100
    return {
        "pivots": {k: round(v, 2) for k, v in piv.items()},
        "prev_pivots": {k: round(v, 2) for k, v in prev_piv.items()},
        "cpr_width_pct": round(cpr_width_pct, 3),
        "supports": [{"price": round(s["price"], 2), "touches": s["touches"]} for s in swings["supports"]],
        "resistances": [{"price": round(s["price"], 2), "touches": s["touches"]} for s in swings["resistances"]],
        "high_52w": round(hi52, 2),
        "low_52w": round(lo52, 2),
        "patterns": candle_patterns(daily),
    }


# ------------------------------------------------------------- timeframes

def day_trading(df: pd.DataFrame, lv: dict) -> dict:
    r = df.iloc[-1]
    c = float(r["close"])
    piv, ppiv = lv["pivots"], lv["prev_pivots"]
    sigs = []

    sigs.append(_sig("Close vs Pivot", piv["P"], 1 if c > piv["P"] else -1,
                     f"Closed {'above' if c > piv['P'] else 'below'} pivot {piv['P']:.2f}"))
    if piv["BC"] > ppiv["TC"]:
        sigs.append(_sig("CPR relation", piv["P"], 1, "Higher-value CPR vs previous session (bullish)"))
    elif piv["TC"] < ppiv["BC"]:
        sigs.append(_sig("CPR relation", piv["P"], -1, "Lower-value CPR vs previous session (bearish)"))
    else:
        sigs.append(_sig("CPR relation", piv["P"], 0, "Overlapping CPR — likely range-bound session"))

    e9, e21 = _v(r, "ema9"), _v(r, "ema21")
    if e9 and e21:
        sigs.append(_sig("EMA 9 / 21", e9 - e21, 1 if e9 > e21 else -1,
                         f"EMA9 {'above' if e9 > e21 else 'below'} EMA21"))
    rsi = _v(r, "rsi")
    if rsi is not None:
        if rsi > 78:
            b, note = -1, "Overbought — pullback risk"
        elif rsi < 22:
            b, note = 1, "Oversold — bounce possible"
        elif rsi >= 60:
            b, note = 1, "Bullish momentum zone (>60)"
        elif rsi <= 40:
            b, note = -1, "Bearish momentum zone (<40)"
        else:
            b, note = 0, "Neutral momentum (40–60)"
        sigs.append(_sig("RSI 14", rsi, b, note))
    k, d = _v(r, "stoch_k"), _v(r, "stoch_d")
    if k is not None and d is not None:
        if k > 80 and k < d:
            b, note = -1, "Stochastic rolling over from overbought"
        elif k < 20 and k > d:
            b, note = 1, "Stochastic turning up from oversold"
        else:
            b, note = (1, "%K above %D") if k > d else (-1, "%K below %D")
        sigs.append(_sig("Stochastic %K", k, b, note))
    st = _v(r, "st_dir")
    if st is not None:
        sigs.append(_sig("Supertrend (10,3)", _v(r, "supertrend"), int(st),
                         f"Supertrend {'buy' if st > 0 else 'sell'} mode"))
    vw = _v(r, "vwap")
    if vw:
        sigs.append(_sig("Close vs VWAP", vw, 1 if c > vw else -1, f"{'Above' if c > vw else 'Below'} VWAP {vw:.2f}"))
    for p in lv["patterns"]:
        if p["bias"]:
            sigs.append(_sig(f"Candle: {p['name']}", None, p["bias"], p["note"]))

    score = _score(sigs)
    atr = _v(r, "atr") or c * 0.015
    bias = "long" if score >= 25 else "short" if score <= -25 else "neutral"
    if bias == "long":
        entry = round(max(c, r["high"]) if score < 60 else c, 2)
        sl = round(max(entry - atr, piv["S1"]) if piv["S1"] < entry - 0.3 * atr else entry - atr, 2)
        tgts = [t for t in (piv["R1"], piv["R2"], piv["R3"]) if t > entry * 1.002][:2] or [entry + atr, entry + 2 * atr]
        note = "Buy on strength above previous high; trail stop to entry after first target. Exit before close."
    elif bias == "short":
        entry = round(min(c, r["low"]) if score > -60 else c, 2)
        sl = round(min(entry + atr, piv["R1"]) if piv["R1"] > entry + 0.3 * atr else entry + atr, 2)
        tgts = [t for t in (piv["S1"], piv["S2"], piv["S3"]) if t < entry * 0.998][:2] or [entry - atr, entry - 2 * atr]
        note = "Sell on weakness below previous low (intraday short/F&O only). Exit before close."
    else:
        entry, sl, tgts = round(piv["S1"], 2), round(piv["S1"] - 0.5 * atr, 2), [piv["P"], piv["R1"]]
        note = f"No clear edge — range trade S1 {piv['S1']:.2f} ↔ R1 {piv['R1']:.2f}, or wait for a breakout."
    tgts = [round(float(t), 2) for t in tgts]
    if lv["cpr_width_pct"] < 0.25:
        note += " Narrow CPR → trending session likely."
    elif lv["cpr_width_pct"] > 0.75:
        note += " Wide CPR → sideways session likely."
    return {
        "score": round(score, 1), "verdict": verdict(score), "signals": sigs,
        "plan": {"bias": bias, "entry": entry, "stop_loss": sl, "targets": tgts,
                 "risk_reward": _rr(entry, sl, tgts[0]), "note": note},
    }


def short_term(df: pd.DataFrame, lv: dict) -> dict:
    r = df.iloc[-1]
    c = float(r["close"])
    sigs = []
    e21, e50 = _v(r, "ema21"), _v(r, "ema50")
    if e21:
        sigs.append(_sig("Close vs EMA21", e21, 1 if c > e21 else -1, f"{'Above' if c > e21 else 'Below'} EMA21"))
    if e21 and e50:
        sigs.append(_sig("EMA 21 / 50", e21 - e50, 1 if e21 > e50 else -1,
                         "Short-term uptrend" if e21 > e50 else "Short-term downtrend"))
    m, ms, mh = _v(r, "macd"), _v(r, "macd_signal"), _v(r, "macd_hist")
    if m is not None and ms is not None:
        sigs.append(_sig("MACD vs Signal", m - ms, 1 if m > ms else -1,
                         "MACD above signal" if m > ms else "MACD below signal"))
        prev_h = df["macd_hist"].iloc[-4] if len(df) > 4 else None
        if mh is not None and prev_h is not None and not pd.isna(prev_h):
            sigs.append(_sig("MACD histogram", mh, 1 if mh > prev_h else -1,
                             "Momentum improving" if mh > prev_h else "Momentum fading"))
    rsi = _v(r, "rsi")
    if rsi is not None:
        b = -1 if rsi > 75 else 1 if rsi < 25 else (1 if rsi > 50 else -1)
        sigs.append(_sig("RSI 14 (50-line)", rsi, b,
                         "Overbought" if rsi > 75 else "Oversold" if rsi < 25 else
                         ("Above 50 — bulls in control" if rsi > 50 else "Below 50 — bears in control")))
    pb = _v(r, "bb_pctb")
    if pb is not None:
        if pb > 1:
            b, note = 1, "Closing above upper band — breakout strength"
        elif pb < 0:
            b, note = -1, "Closing below lower band — breakdown"
        elif pb > 0.5:
            b, note = 1, "Upper half of Bollinger Bands"
        else:
            b, note = -1, "Lower half of Bollinger Bands"
        sigs.append(_sig("Bollinger %B", pb, b, note))
    ax, pdi, mdi = _v(r, "adx"), _v(r, "plus_di"), _v(r, "minus_di")
    if ax is not None and pdi is not None:
        if ax >= 25:
            sigs.append(_sig("ADX / DMI", ax, 1 if pdi > mdi else -1,
                             f"Trending (ADX {ax:.0f}) — {'+DI' if pdi > mdi else '-DI'} dominant"))
        else:
            sigs.append(_sig("ADX / DMI", ax, 0, f"Weak trend (ADX {ax:.0f}) — range-bound"))
    vr = df["volume"].tail(5).mean() / (_v(r, "vol_sma20") or np.nan)
    ret5 = c / df["close"].iloc[-6] - 1 if len(df) > 6 else 0
    if not math.isnan(vr):
        b = (1 if ret5 > 0 else -1) if vr > 1.2 else 0
        sigs.append(_sig("Volume (5d vs 20d)", vr, b,
                         f"Volume {vr:.1f}x average {'confirming' if b else '— no confirmation'}"
                         f"{' up-move' if b > 0 else ' down-move' if b < 0 else ''}"))
    if len(df) > 21:
        r20 = (c / df["close"].iloc[-21] - 1) * 100
        sigs.append(_sig("20-session return %", r20, 1 if r20 > 2 else -1 if r20 < -2 else 0, f"{r20:+.1f}% over 20 sessions"))

    score = _score(sigs)
    atr = _v(r, "atr") or c * 0.02
    sup = [s["price"] for s in lv["supports"]]
    res = [s["price"] for s in lv["resistances"]]
    bias = "long" if score >= 25 else "short" if score <= -25 else "neutral"
    if bias == "long":
        entry = c
        near = sup[0] if sup and c - sup[0] < 3 * atr else None
        sl = (near - 0.25 * atr) if near else c - 2 * atr
        tgts = [t for t in res if t > c * 1.01][:2] or [c + 2 * atr, c + 4 * atr]
        note = "Swing buy; consider buying dips toward EMA21. Holding period ~1–4 weeks."
    elif bias == "short":
        entry = c
        near = res[0] if res and res[0] - c < 3 * atr else None
        sl = (near + 0.25 * atr) if near else c + 2 * atr
        tgts = [t for t in sup if t < c * 0.99][:2] or [c - 2 * atr, c - 4 * atr]
        note = "Avoid fresh longs; existing holders can book profits on bounces. Shorting only via F&O."
    else:
        entry = c
        sl = c - 2 * atr
        tgts = [res[0]] if res else [c + 2 * atr]
        note = "Mixed signals — wait for EMA21/50 alignment or a MACD crossover."
    tgts = [round(float(t), 2) for t in tgts]
    return {"score": round(score, 1), "verdict": verdict(score), "signals": sigs,
            "plan": {"bias": bias, "entry": round(entry, 2), "stop_loss": round(sl, 2), "targets": tgts,
                     "risk_reward": _rr(entry, sl, tgts[0]), "note": note}}


def long_term(df: pd.DataFrame, lv: dict, intraday: bool) -> dict:
    daily = session_bars(df, intraday) if intraday else df
    r = df.iloc[-1]
    c = float(r["close"])
    sigs = []
    notes = []
    s50, s200 = _v(r, "sma50"), _v(r, "sma200")
    if intraday:
        notes.append("Intraday upload — long-term view uses resampled daily bars; upload ≥1 year of daily data for best results.")
        s50 = float(daily["close"].rolling(50).mean().iloc[-1]) if len(daily) >= 50 else None
        s200 = float(daily["close"].rolling(200).mean().iloc[-1]) if len(daily) >= 200 else None
    if s200:
        sigs.append(_sig("Close vs SMA200", s200, 1 if c > s200 else -1,
                         f"{(c / s200 - 1) * 100:+.1f}% vs 200-day average"))
        prev200 = df["sma200"].iloc[-21] if not intraday and len(df) > 221 else None
        if prev200 is not None and not pd.isna(prev200):
            sigs.append(_sig("SMA200 slope (1M)", (s200 / prev200 - 1) * 100, 1 if s200 > prev200 else -1,
                             "200-day average rising" if s200 > prev200 else "200-day average falling"))
    else:
        notes.append("Fewer than 200 sessions — SMA200 signals skipped.")
    if s50 and s200:
        cross = ""
        if not intraday:
            diff = (df["sma50"] - df["sma200"]).tail(20).dropna()
            if len(diff) > 1 and np.sign(diff.iloc[0]) != np.sign(diff.iloc[-1]):
                cross = " — fresh Golden Cross" if diff.iloc[-1] > 0 else " — fresh Death Cross"
        sigs.append(_sig("SMA 50 / 200", s50 - s200, 1 if s50 > s200 else -1,
                         ("Golden-cross regime" if s50 > s200 else "Death-cross regime") + cross))
    elif s50:
        sigs.append(_sig("Close vs SMA50", s50, 1 if c > s50 else -1, f"{'Above' if c > s50 else 'Below'} 50-day average"))
    hi, lo = lv["high_52w"], lv["low_52w"]
    if hi > lo:
        pos = (c - lo) / (hi - lo)
        sigs.append(_sig("52-week range position", pos * 100, 1 if pos > 0.6 else -1 if pos < 0.3 else 0,
                         f"{(c / hi - 1) * 100:+.1f}% from 52W high, {(c / lo - 1) * 100:+.1f}% from 52W low"))
    for label, n in (("6-month return %", 126), ("12-month return %", 252)):
        if len(daily) > n:
            ret = (c / daily["close"].iloc[-n - 1] - 1) * 100
            sigs.append(_sig(label, ret, 1 if ret > 5 else -1 if ret < -5 else 0, f"{ret:+.1f}%"))
    obv_s = df["obv"]
    if len(obv_s) > 60:
        o_ma = obv_s.rolling(50).mean().iloc[-1]
        sigs.append(_sig("OBV vs 50-avg", None, 1 if obv_s.iloc[-1] > o_ma else -1,
                         "Accumulation (OBV above average)" if obv_s.iloc[-1] > o_ma else "Distribution (OBV below average)"))
    vol = daily["close"].pct_change().tail(252).std() * math.sqrt(252) * 100
    score = _score(sigs)
    bias = "long" if score >= 25 else "short" if score <= -25 else "neutral"
    atr = _v(r, "atr") or c * 0.02
    if bias == "long":
        zone_low = round(min(c, s50 or c - 2 * atr), 2)
        sl = round((s200 * 0.97) if s200 and s200 < c else c * 0.88, 2)
        tgts = [round(max(hi, c * 1.1), 2), round(c * 1.25, 2)]
        note = f"Accumulate on dips toward {zone_low}; review if price closes below the 200-day average."
    elif bias == "short":
        sl = round((s200 * 1.03) if s200 and s200 > c else c * 1.12, 2)
        tgts = [round(lo, 2) if lo < c else round(c * 0.9, 2)]
        note = "Long-term trend weak — avoid fresh investment; reduce on rallies toward the 50/200-day averages."
    else:
        sl = round(c * 0.88, 2)
        tgts = [round(hi, 2)]
        note = "Sideways long-term structure — SIP-style staggered buying only, or wait for a trend."
    return {"score": round(score, 1), "verdict": verdict(score), "signals": sigs,
            "annualized_volatility_pct": None if pd.isna(vol) else round(float(vol), 1), "notes": notes,
            "plan": {"bias": bias, "entry": round(c, 2), "stop_loss": sl, "targets": tgts,
                     "risk_reward": _rr(c, sl, tgts[0]), "note": note}}


def combine(tech_score: float, ml: dict) -> dict:
    """Blend the rule score (-100..100) with the ML probability, weighting ML by its validated edge."""
    if not ml.get("available"):
        return {"score": round(tech_score, 1), "verdict": verdict(tech_score), "ml_weight": 0.0}
    ml_score = (ml["prob_up"] - 0.5) * 200
    w = 0.4 if ml.get("has_edge") else 0.15
    s = (1 - w) * tech_score + w * ml_score
    return {"score": round(s, 1), "verdict": verdict(s), "ml_weight": w}
