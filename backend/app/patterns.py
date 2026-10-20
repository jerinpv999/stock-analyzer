"""Candlestick pattern detection + pattern prediction model.

1. `detect()` scans every bar for 22 classic one-, two- and three-candle patterns
   (vectorised, with trend context so e.g. a Hammer is only a Hammer after a decline).
2. `pattern_stats()` measures how each pattern actually played out on *this* stock:
   occurrences, win rate and average move 1/3/5/10 sessions later.
3. `PatternModel` learns P(pattern succeeds within 3 sessions) from pattern type +
   context (RSI, trend, volume, position in range...). It is trained on every pattern
   event across *all* stocks you have uploaded (pooled), because patterns behave
   similarly across stocks and one stock alone has too few events. It is validated
   walk-forward in date order and compared against the base success rate.
"""
from __future__ import annotations

import logging
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from .config import HISTORY_DIR, MODEL_DIR

log = logging.getLogger(__name__)

PATTERN_HORIZON = 3  # sessions used to judge a pattern's success

PATTERNS: dict[str, tuple[int, int, str]] = {
    # name: (bias, candles, description)
    "Doji": (0, 1, "Open ≈ close; indecision. Direction comes from the next candle."),
    "Spinning Top": (0, 1, "Small body, wicks both sides; balance between buyers and sellers."),
    "Dragonfly Doji": (1, 1, "Doji with a long lower wick after a decline; sellers rejected."),
    "Gravestone Doji": (-1, 1, "Doji with a long upper wick after a rally; buyers rejected."),
    "Hammer": (1, 1, "Small body, long lower wick after a decline; potential bottom."),
    "Hanging Man": (-1, 1, "Hammer shape after a rally; early warning of weakness."),
    "Inverted Hammer": (1, 1, "Long upper wick after a decline; buyers testing higher."),
    "Shooting Star": (-1, 1, "Long upper wick after a rally; rejection of higher prices."),
    "Bullish Marubozu": (1, 1, "Large green body with almost no wicks; strong buying."),
    "Bearish Marubozu": (-1, 1, "Large red body with almost no wicks; strong selling."),
    "Bullish Engulfing": (1, 2, "Green body fully engulfs the prior red body after a decline."),
    "Bearish Engulfing": (-1, 2, "Red body fully engulfs the prior green body after a rally."),
    "Bullish Harami": (1, 2, "Small green body inside a large prior red body; selling pausing."),
    "Bearish Harami": (-1, 2, "Small red body inside a large prior green body; buying pausing."),
    "Piercing Line": (1, 2, "Green candle closes above the midpoint of a prior large red candle."),
    "Dark Cloud Cover": (-1, 2, "Red candle closes below the midpoint of a prior large green candle."),
    "Tweezer Bottom": (1, 2, "Two candles with matching lows after a decline; support confirmed."),
    "Tweezer Top": (-1, 2, "Two candles with matching highs after a rally; resistance confirmed."),
    "Morning Star": (1, 3, "Large red, small-body star, then strong green; three-candle reversal up."),
    "Evening Star": (-1, 3, "Large green, small-body star, then strong red; three-candle reversal down."),
    "Three White Soldiers": (1, 3, "Three strong green candles with higher closes; sustained buying."),
    "Three Black Crows": (-1, 3, "Three strong red candles with lower closes; sustained selling."),
}
BIAS = {k: v[0] for k, v in PATTERNS.items()}
DIRECTIONAL = [k for k, v in PATTERNS.items() if v[0] != 0]
SHORT = {k: "".join(w[0] for w in k.split()) for k in PATTERNS}  # chart marker labels, e.g. "BE"


def detect(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0, np.nan)
    body = (c - o).abs()
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    bull, bear = c > o, c < o
    avg_body = body.rolling(10, min_periods=5).mean()
    ema10 = c.ewm(span=10, adjust=False).mean()
    down = (c.shift(1) < ema10.shift(1)) & (c.shift(1) < c.shift(6))
    up = (c.shift(1) > ema10.shift(1)) & (c.shift(1) > c.shift(6))

    po, pc, ph, pl = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    pbody = (pc - po).abs()
    prng = (ph - pl).replace(0, np.nan)
    pbull, pbear = pc > po, pc < po
    o2, c2 = o.shift(2), c.shift(2)
    b2 = (c2 - o2).abs()
    rng2 = (h.shift(2) - l.shift(2)).replace(0, np.nan)

    small = body <= 0.1 * rng
    hammer_shape = (lower >= 2 * body) & (upper <= 0.3 * rng) & (body > 0.1 * rng)
    inv_shape = (upper >= 2 * body) & (lower <= 0.3 * rng) & (body > 0.1 * rng)
    maru = (body >= 0.9 * rng) & (body > 1.2 * avg_body)
    tol = 0.002 * c

    d = {
        "Doji": small & (upper > 0.25 * rng) & (lower > 0.25 * rng),
        "Spinning Top": (body > 0.1 * rng) & (body <= 0.3 * rng) & (upper > body) & (lower > body),
        "Dragonfly Doji": small & (lower >= 0.6 * rng) & (upper <= 0.1 * rng) & down,
        "Gravestone Doji": small & (upper >= 0.6 * rng) & (lower <= 0.1 * rng) & up,
        "Hammer": hammer_shape & down,
        "Hanging Man": hammer_shape & up,
        "Inverted Hammer": inv_shape & down,
        "Shooting Star": inv_shape & up,
        "Bullish Marubozu": maru & bull,
        "Bearish Marubozu": maru & bear,
        "Bullish Engulfing": pbear & bull & (c >= po) & (o <= pc) & (body > pbody) & down,
        "Bearish Engulfing": pbull & bear & (c <= po) & (o >= pc) & (body > pbody) & up,
        "Bullish Harami": pbear & bull & (pbody > avg_body) & (o >= pc) & (c <= po) & (body < 0.6 * pbody) & down,
        "Bearish Harami": pbull & bear & (pbody > avg_body) & (o <= pc) & (c >= po) & (body < 0.6 * pbody) & up,
        "Piercing Line": pbear & bull & (pbody > avg_body) & (o < pc) & (c > (po + pc) / 2) & (c < po) & down,
        "Dark Cloud Cover": pbull & bear & (pbody > avg_body) & (o > pc) & (c < (po + pc) / 2) & (c > po) & up,
        "Tweezer Bottom": ((l - pl).abs() <= tol) & pbear & bull & down,
        "Tweezer Top": ((h - ph).abs() <= tol) & pbull & bear & up,
        "Morning Star": (c2 < o2) & (b2 > avg_body) & (pbody < 0.5 * b2) & bull & (c > (o2 + c2) / 2) & down.shift(1, fill_value=False),
        "Evening Star": (c2 > o2) & (b2 > avg_body) & (pbody < 0.5 * b2) & bear & (c < (o2 + c2) / 2) & up.shift(1, fill_value=False),
        "Three White Soldiers": bull & pbull & (c2 > o2) & (c > pc) & (pc > c2) & (o > po) & (po > o2)
                                & (body > 0.6 * rng) & (pbody > 0.6 * prng) & (b2 > 0.6 * rng2),
        "Three Black Crows": bear & pbear & (c2 < o2) & (c < pc) & (pc < c2) & (o < po) & (po < o2)
                             & (body > 0.6 * rng) & (pbody > 0.6 * prng) & (b2 > 0.6 * rng2),
    }
    out = pd.DataFrame(d, index=df.index).fillna(False).astype(bool)
    # a candle can't be both a Doji and a Dragonfly/Gravestone — keep the more specific one
    out.loc[out["Dragonfly Doji"] | out["Gravestone Doji"], "Doji"] = False
    return out


def pattern_columns(pats: pd.DataFrame) -> pd.DataFrame:
    """Compact numeric summary for other models: bullish/bearish pattern counts."""
    bias = pd.Series(BIAS)
    signed = pats.astype(int).mul(bias[pats.columns], axis=1)
    return pd.DataFrame({
        "pat_bull": (signed > 0).sum(axis=1),
        "pat_bear": (signed < 0).sum(axis=1),
    }, index=pats.index)


def names_on(pats: pd.DataFrame, i: int = -1) -> list[str]:
    row = pats.iloc[i]
    return [k for k in pats.columns if row[k]]


def latest_patterns(df: pd.DataFrame) -> list[dict]:
    pats = detect(df)
    return [{"name": n, "bias": BIAS[n], "note": PATTERNS[n][2]} for n in names_on(pats)]


# ------------------------------------------------------------------ per-stock statistics

def pattern_stats(df: pd.DataFrame, pats: pd.DataFrame) -> list[dict]:
    c = df["close"]
    rows = []
    for name in pats.columns:
        mask = pats[name]
        n = int(mask.sum())
        if n == 0:
            continue
        bias = BIAS[name]
        r = {"pattern": name, "bias": bias, "candles": PATTERNS[name][1], "occurrences": n,
             "last_seen": pats.index[mask][-1].isoformat()}
        for hz in (1, 3, 5, 10):
            fwd = (c.shift(-hz) / c - 1)[mask].dropna()
            if fwd.empty:
                continue
            r[f"avg_move_{hz}"] = float(fwd.mean() * 100)
            if bias:
                wins = int(((fwd > 0) if bias > 0 else (fwd < 0)).sum())
                r[f"win_rate_{hz}"] = wins / len(fwd)
                r[f"evaluated_{hz}"] = len(fwd)
                if hz == PATTERN_HORIZON:
                    # shrink toward 50% when there are few samples (Bayesian prior worth 6 events)
                    r["win_rate_smoothed"] = (wins + 3) / (len(fwd) + 6)
            else:
                r[f"up_rate_{hz}"] = float((fwd > 0).mean())
        rows.append(r)
    rows.sort(key=lambda x: -x["occurrences"])
    return rows


def recent_occurrences(df: pd.DataFrame, pats: pd.DataFrame, bars: int) -> list[dict]:
    """Directional patterns within the charted window (for markers)."""
    tail = pats[DIRECTIONAL].tail(bars)
    c = df["close"]
    out = []
    for ts, row in tail.iterrows():
        hits = [k for k in DIRECTIONAL if row[k]]
        if not hits:
            continue
        pos = df.index.get_loc(ts)
        after = c.iloc[pos + PATTERN_HORIZON] if pos + PATTERN_HORIZON < len(c) else None
        net = sum(BIAS[k] for k in hits)
        out.append({
            "ts": ts, "patterns": hits, "short": "/".join(SHORT[k] for k in hits),
            "bias": int(np.sign(net)),
            "move_after_pct": None if after is None else float((after / c.iloc[pos] - 1) * 100),
        })
    return out


# ------------------------------------------------------------------ prediction model

CONTEXT = ["rsi_n", "dist_ema21", "dist_sma50", "vol_ratio", "atr_n", "bb_pctb", "close_pos",
           "ret5_prior", "adx_n", "di_diff", "dist_low20", "dist_high20", "body_n", "st_dir"]


def _event_frame(ind: pd.DataFrame, pats: pd.DataFrame, symbol: str) -> pd.DataFrame:
    c = ind["close"]
    bias = pd.Series(BIAS)
    signed = pats[DIRECTIONAL].astype(int).mul(bias[DIRECTIONAL], axis=1).sum(axis=1)
    f = pd.DataFrame(index=ind.index)
    f["rsi_n"] = ind["rsi"] / 100
    f["dist_ema21"] = c / ind["ema21"] - 1
    f["dist_sma50"] = c / ind["sma50"] - 1
    f["vol_ratio"] = ind["volume"] / ind["vol_sma20"]
    f["atr_n"] = ind["atr"] / c
    f["bb_pctb"] = ind["bb_pctb"]
    f["close_pos"] = (c - ind["low"]) / (ind["high"] - ind["low"]).replace(0, np.nan)
    f["ret5_prior"] = c.shift(1) / c.shift(6) - 1
    f["adx_n"] = ind["adx"] / 100
    f["di_diff"] = (ind["plus_di"] - ind["minus_di"]) / 100
    f["dist_low20"] = c / ind["low"].rolling(20).min() - 1
    f["dist_high20"] = c / ind["high"].rolling(20).max() - 1
    f["body_n"] = (c - ind["open"]).abs() / ind["atr"]
    f["st_dir"] = ind["st_dir"]
    # context is expressed relative to the pattern's direction, so bullish and bearish
    # events share one model ("how stretched is price *in the pattern's favour*")
    sgn = np.sign(signed).replace(0, np.nan)
    for col in ("dist_ema21", "dist_sma50", "ret5_prior", "di_diff", "st_dir"):
        f[col] = f[col] * sgn
    f["rsi_n"] = np.where(sgn > 0, f["rsi_n"], 1 - f["rsi_n"])
    f["bb_pctb"] = np.where(sgn > 0, f["bb_pctb"], 1 - f["bb_pctb"])
    f["close_pos"] = np.where(sgn > 0, f["close_pos"], 1 - f["close_pos"])
    for k in DIRECTIONAL:
        f[f"p_{k}"] = pats[k].astype(int)
    f["signed"] = signed
    fwd = c.shift(-PATTERN_HORIZON) / c - 1
    f["target"] = np.where(fwd.isna(), np.nan, (np.sign(fwd) == np.sign(signed)).astype(float))
    f["symbol"] = symbol
    f["date"] = ind.index
    f = f.replace([np.inf, -np.inf], np.nan)
    f.index.name = None
    return f[signed != 0]


def _model():
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_depth=3, min_samples_leaf=15,
                                          l2_regularization=1.0, random_state=7)


def _usable(X: pd.DataFrame) -> list[str]:
    return [c for c in X.columns if X[c].nunique(dropna=True) >= 2]


def _prediction_text(names: list[str], direction: int, p: float) -> str:
    kind = "bullish" if direction > 0 else "bearish"
    move = "higher" if direction > 0 else "lower"
    head = f"{' + '.join(names)} ({kind})"
    if p >= 0.53:
        return f"{head}: {p * 100:.0f}% estimated chance price is {move} in {PATTERN_HORIZON} sessions."
    if p > 0.47:
        return f"{head}: close to a coin flip ({p * 100:.0f}%) — wait for confirmation before acting on it."
    return (f"{head}: historically unreliable in this context — only {p * 100:.0f}% chance price is {move} "
            f"in {PATTERN_HORIZON} sessions; don't trade it on its own.")


class PatternModel:
    MIN_EVENTS = 80

    def __init__(self, add_indicators):
        self.add_indicators = add_indicators  # injected to avoid a circular import

    def _pool(self, current_symbol: str, current_ind: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        frames = [_event_frame(current_ind, detect(current_ind), current_symbol)]
        used = [current_symbol]
        for path in HISTORY_DIR.glob("*_daily.csv"):
            sym = path.stem.rsplit("_", 1)[0]
            if sym == current_symbol:
                continue
            try:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                if len(df) < 60:
                    continue
                ind = self.add_indicators(df, False)
                frames.append(_event_frame(ind, detect(ind), sym))
                used.append(sym)
            except Exception as e:  # noqa: BLE001
                log.warning("skipping %s for pattern model: %s", path.name, e)
        return pd.concat(frames, ignore_index=True).sort_values("date", kind="stable").reset_index(drop=True), used

    def run(self, symbol: str, ind: pd.DataFrame, pats: pd.DataFrame, stats: list[dict]) -> dict:
        today = names_on(pats)
        today_dir = [n for n in today if BIAS[n]]
        events, used = self._pool(symbol, ind)
        labelled = events[events["target"].notna()]
        feat_cols = [c for c in events.columns if c not in ("target", "symbol", "date")]
        info = {"horizon_sessions": PATTERN_HORIZON, "stocks_in_pool": used, "events": int(len(labelled))}

        model_ok = len(labelled) >= self.MIN_EVENTS and labelled["target"].nunique() == 2
        if model_ok:
            X, y = labelled[feat_cols], labelled["target"].astype(int)
            accs, bases, aucs = [], [], []
            for tr, te in TimeSeriesSplit(n_splits=4, gap=PATTERN_HORIZON).split(X):
                if y.iloc[tr].nunique() < 2:
                    continue
                cols = _usable(X.iloc[tr])
                m = _model().fit(X.iloc[tr][cols], y.iloc[tr])
                p = m.predict_proba(X.iloc[te][cols])[:, 1]
                accs.append(accuracy_score(y.iloc[te], (p >= 0.5).astype(int)))
                bases.append(float((y.iloc[te] == int(y.iloc[tr].mean() >= 0.5)).mean()))
                if y.iloc[te].nunique() == 2:
                    aucs.append(roc_auc_score(y.iloc[te], p))
            cols = _usable(X)
            model = _model().fit(X[cols], y)
            joblib.dump({"model": model, "features": cols, "trained_at": datetime.now().isoformat(),
                         "events": len(X), "stocks": used}, MODEL_DIR / "candlestick_pattern_model.joblib")
            acc = float(np.mean(accs)) if accs else None
            base = float(np.mean(bases)) if bases else None
            info.update({
                "available": True, "cv_accuracy": acc, "baseline_accuracy": base,
                "cv_auc": float(np.mean(aucs)) if aucs else None,
                "base_success_rate": float(y.mean()),
                "has_edge": bool(acc is not None and base is not None and acc - base > 0.02),
            })
        else:
            model, cols = None, []
            info.update({"available": False,
                         "reason": f"Only {len(labelled)} labelled pattern events across uploaded stocks "
                                   f"(need {self.MIN_EVENTS}). Using this stock's pattern statistics only. "
                                   "Uploading more history or more stocks enables the model."})

        by_name = {s["pattern"]: s for s in stats}
        signals = []
        for n in today:
            st = by_name.get(n, {})
            sig = {"name": n, "bias": BIAS[n], "candles": PATTERNS[n][1], "description": PATTERNS[n][2],
                   "occurrences_this_stock": st.get("occurrences", 0),
                   "hist_win_rate": st.get(f"win_rate_{PATTERN_HORIZON}"),
                   "hist_avg_move_pct": st.get(f"avg_move_{PATTERN_HORIZON}")}
            signals.append(sig)

        prediction = None
        if today_dir:
            net = sum(BIAS[n] for n in today_dir)
            direction = 1 if net > 0 else -1 if net < 0 else 0
            if direction:
                ev_today = events[events["date"] == ind.index[-1]]
                ev_today = ev_today[ev_today["symbol"] == symbol]
                smoothed = [by_name[n].get("win_rate_smoothed") for n in today_dir
                            if n in by_name and by_name[n].get("win_rate_smoothed") is not None]
                stat_p = float(np.mean(smoothed)) if smoothed else 0.5
                if model is not None and not ev_today.empty:
                    model_p = float(model.predict_proba(ev_today[cols].iloc[[-1]])[0, 1])
                    w = 0.6 if info.get("has_edge") else 0.3
                    p_success = w * model_p + (1 - w) * stat_p
                else:
                    model_p, p_success = None, stat_p
                avg_moves = [by_name[n].get(f"avg_move_{PATTERN_HORIZON}") for n in today_dir if n in by_name]
                avg_moves = [m for m in avg_moves if m is not None]
                prediction = {
                    "direction": "Up" if direction > 0 else "Down",
                    "success_probability": p_success,
                    "prob_up": p_success if direction > 0 else 1 - p_success,
                    "model_probability": model_p,
                    "stock_history_probability": stat_p,
                    "expected_move_pct": float(np.mean(avg_moves)) if avg_moves else None,
                    "reliability": "High" if p_success >= 0.6 else "Moderate" if p_success >= 0.53 else "Low",
                    "text": _prediction_text(today_dir, direction, p_success),
                }
            else:
                prediction = {"direction": "Mixed", "text": "Bullish and bearish patterns on the same candle — no signal."}

        return {"today": signals, "prediction": prediction, "model": info}
