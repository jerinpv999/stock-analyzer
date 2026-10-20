"""ML model: gradient-boosted classifier trained on the stock's own history.

For each horizon (1 bar = day trading, 5 = short term, 20 = long term) it learns
P(close[t+h] > close[t]) from technical features, validates with walk-forward
TimeSeriesSplit (with a gap so labels never leak), then refits on all labelled
rows and predicts for the latest bar. Models are saved per symbol/horizon.
"""
from __future__ import annotations

import re
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score
from sklearn.model_selection import TimeSeriesSplit

from .config import MODEL_DIR

HORIZONS = {"day_trading": 1, "short_term": 5, "long_term": 20}
MIN_TRAIN_ROWS = 150


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    for n in (1, 3, 5, 10, 20):
        f[f"ret_{n}"] = c.pct_change(n)
    f["ret_60"] = c.pct_change(60)
    f["rsi"] = df["rsi"] / 100
    f["macd_n"] = df["macd"] / c
    f["macd_hist_n"] = df["macd_hist"] / c
    f["macd_hist_chg"] = df["macd_hist"].diff() / c
    f["bb_pctb"] = df["bb_pctb"]
    f["bb_width"] = df["bb_width"]
    f["atr_n"] = df["atr"] / c
    f["stoch_k"] = df["stoch_k"] / 100
    f["stoch_kd"] = (df["stoch_k"] - df["stoch_d"]) / 100
    f["adx"] = df["adx"] / 100
    f["di_diff"] = (df["plus_di"] - df["minus_di"]) / 100
    f["dist_ema9"] = c / df["ema9"] - 1
    f["dist_ema21"] = c / df["ema21"] - 1
    f["dist_sma50"] = c / df["sma50"] - 1
    f["dist_sma200"] = c / df["sma200"] - 1
    f["ema9_21"] = df["ema9"] / df["ema21"] - 1
    f["vol_ratio"] = df["volume"] / df["vol_sma20"]
    f["range_n"] = (df["high"] - df["low"]) / c
    f["close_pos"] = (c - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)
    f["gap"] = df["open"] / c.shift(1) - 1
    f["st_dir"] = df["st_dir"]
    f["volatility_20"] = c.pct_change().rolling(20).std()
    f["dist_52w_high"] = c / df["high"].rolling(252, min_periods=60).max() - 1
    f["dist_vwap"] = c / df["vwap"] - 1
    f["pat_net"] = df["pat_bull"] - df["pat_bear"]
    f["pat_net_3"] = f["pat_net"].rolling(3).sum()
    return f.replace([np.inf, -np.inf], np.nan)


def _new_model():
    return HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=20,
        l2_regularization=1.0, random_state=42,
    )


def _usable(X: pd.DataFrame) -> list[str]:
    """Columns with at least 2 distinct non-NaN values (sklearn's binner rejects constant/all-NaN columns)."""
    return [c for c in X.columns if X[c].nunique(dropna=True) >= 2]


def _safe(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9&_-]", "_", sym)


def train_and_predict(df: pd.DataFrame, symbol: str, horizon_key: str, intraday: bool) -> dict:
    h = HORIZONS[horizon_key]
    X = build_features(df)
    fwd = df["close"].shift(-h) / df["close"] - 1
    labelled = fwd.notna()
    labelled.iloc[:30] = False  # indicator warm-up
    Xl, yl = X[labelled], (fwd[labelled] > 0).astype(int)

    base = {"horizon_bars": h, "horizon_label": f"{h} {'bar' if intraday else 'session'}{'s' if h > 1 else ''}"}
    if len(Xl) < MIN_TRAIN_ROWS:
        return {**base, "available": False,
                "reason": f"Need ≥{MIN_TRAIN_ROWS} labelled rows for this horizon, have {len(Xl)}. Upload more history."}
    if yl.nunique() < 2:
        return {**base, "available": False, "reason": "Target has only one class in history."}

    n_splits = 5 if len(Xl) >= 500 else 3
    tss = TimeSeriesSplit(n_splits=n_splits, gap=h)
    accs, bases, last_fold = [], [], None
    for tr, te in tss.split(Xl):
        if yl.iloc[tr].nunique() < 2:
            continue
        cols = _usable(Xl.iloc[tr])
        m = _new_model().fit(Xl.iloc[tr][cols], yl.iloc[tr])
        pred = m.predict(Xl.iloc[te][cols])
        accs.append(accuracy_score(yl.iloc[te], pred))
        # baseline: always predict the majority class seen in training
        maj = int(yl.iloc[tr].mean() >= 0.5)
        bases.append(float((yl.iloc[te] == maj).mean()))
        last_fold = (m, te, cols)

    cols_all = _usable(Xl)
    model = _new_model().fit(Xl[cols_all], yl)
    latest = X.iloc[[-1]][cols_all]
    prob_up = float(model.predict_proba(latest)[0, 1])

    importances = []
    if last_fold is not None:
        m, te, cols = last_fold
        try:
            pi = permutation_importance(m, Xl.iloc[te][cols], yl.iloc[te], n_repeats=3, random_state=0)
            order = np.argsort(pi.importances_mean)[::-1][:6]
            importances = [{"feature": cols[i], "importance": float(pi.importances_mean[i])}
                           for i in order if pi.importances_mean[i] > 0]
        except Exception:  # noqa: BLE001
            pass

    acc = float(np.mean(accs)) if accs else None
    baseline = float(np.mean(bases)) if bases else None
    edge = (acc - baseline) if acc is not None and baseline is not None else None
    abs_moves = fwd[labelled].abs()

    path = MODEL_DIR / f"{_safe(symbol)}_{'intraday' if intraday else 'daily'}_{horizon_key}.joblib"
    joblib.dump({"model": model, "features": cols_all, "horizon": h,
                 "trained_at": datetime.now().isoformat(), "rows": int(len(Xl))}, path)

    return {
        **base,
        "available": True,
        "prob_up": prob_up,
        "direction": "Up" if prob_up >= 0.5 else "Down",
        "confidence": abs(prob_up - 0.5) * 2,
        "cv_accuracy": acc,
        "baseline_accuracy": baseline,
        "edge": edge,
        "has_edge": bool(edge is not None and edge > 0.02),
        "train_rows": int(len(Xl)),
        "up_rate_history": float(yl.mean()),
        "median_abs_move_pct": float(abs_moves.median() * 100),
        "top_features": importances,
        "model_file": path.name,
    }
