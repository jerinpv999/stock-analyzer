"""Pre-market outlook model (offline): P(Nifty opens above yesterday's close) and
P(Nifty closes above yesterday's close), from overnight global cues.

No look-ahead: for an Indian session on date t, every input is the latest value dated
strictly before t (US/Europe/Asia closes of t-1 have all finished before 08:15 IST).
Logistic regression on standardised 1-day moves — simple, stable with ~1,200 rows, and
its coefficients explain each prediction. Validated walk-forward against a naive baseline.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..config import MODEL_DIR
from .sources import FetchError, Http, yahoo_chart
from .universe import GLOBAL, MODEL_INPUTS, NIFTY

log = logging.getLogger(__name__)
NAMES = {s: n for s, n, *_ in GLOBAL}
NAMES[NIFTY] = "Nifty 50"
MODEL_PATH = MODEL_DIR / "premarket_outlook.joblib"


def load_history(http: Http, rng: str = "5y") -> dict[str, pd.DataFrame]:
    hist = {}
    for sym in [NIFTY] + MODEL_INPUTS:
        try:
            hist[sym] = yahoo_chart(http, sym, rng=rng, max_age_h=20)
        except FetchError as e:
            log.warning("history %s unavailable: %s", sym, e)
    return hist


def _asof(dates: pd.DatetimeIndex, s: pd.Series, max_gap_days: int = 6) -> pd.Series:
    """For each date, the value of `s` on its last date strictly before it (no look-ahead)."""
    s = s.dropna()
    left = pd.DataFrame({"d": dates})
    right = pd.DataFrame({"d": s.index, "v": s.values}).sort_values("d")
    m = pd.merge_asof(left, right, on="d", allow_exact_matches=False, direction="backward",
                      tolerance=pd.Timedelta(days=max_gap_days))
    return pd.Series(m["v"].values, index=dates)


def build_frame(hist: dict[str, pd.DataFrame], extra_dates: list[pd.Timestamp] | None = None) -> pd.DataFrame:
    n = hist[NIFTY]
    dates = n.index
    if extra_dates:
        dates = dates.union(pd.DatetimeIndex(extra_dates))
    X = pd.DataFrame(index=dates)
    for sym in MODEL_INPUTS:
        if sym in hist and len(hist[sym]) > 30:
            X[f"ret_{sym}"] = _asof(dates, hist[sym]["close"].pct_change())
    X["nifty_ret1"] = _asof(dates, n["close"].pct_change())
    X["nifty_ret5"] = _asof(dates, n["close"].pct_change(5))
    X["prev_close"] = _asof(dates, n["close"], max_gap_days=10)
    today_open, today_close = n["open"].reindex(dates), n["close"].reindex(dates)
    X["gap_up"] = np.where(today_open.notna() & X["prev_close"].notna(), (today_open > X["prev_close"]).astype(float), np.nan)
    X["close_up"] = np.where(today_close.notna() & X["prev_close"].notna(), (today_close > X["prev_close"]).astype(float), np.nan)
    return X


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=500))


def train_and_predict(hist: dict[str, pd.DataFrame], for_date: date) -> dict:
    if NIFTY not in hist or len(hist[NIFTY]) < 300:
        return {"available": False, "reason": "Not enough Nifty history from Yahoo Finance to train the model."}
    target_day = pd.Timestamp(for_date)
    F = build_frame(hist, [target_day])
    feats = [c for c in F.columns if c.startswith("ret_") or c.startswith("nifty_")]
    out = {"available": True, "for_date": for_date.isoformat(), "features": len(feats), "targets": {}}
    row = F.loc[[target_day], feats]
    if row.isna().all(axis=1).iloc[0]:
        return {"available": False, "reason": "No overnight data available yet."}
    saved = {}
    for target, label in (("gap_up", "Opens higher (gap-up)"), ("close_up", "Closes higher")):
        d = F[F.index < target_day].dropna(subset=[target])
        d = d.dropna(subset=feats, thresh=len(feats) - 2)
        d = d.iloc[-1500:]
        Xd, y = d[feats].fillna(0.0), d[target].astype(int)
        if len(d) < 250 or y.nunique() < 2:
            out["targets"][target] = {"available": False, "reason": "not enough training rows"}
            continue
        accs, bases, aucs = [], [], []
        for tr, te in TimeSeriesSplit(n_splits=5).split(Xd):
            m = _model().fit(Xd.iloc[tr], y.iloc[tr])
            p = m.predict_proba(Xd.iloc[te])[:, 1]
            accs.append(accuracy_score(y.iloc[te], (p >= 0.5).astype(int)))
            bases.append(float((y.iloc[te] == int(y.iloc[tr].mean() >= 0.5)).mean()))
            if y.iloc[te].nunique() == 2:
                aucs.append(roc_auc_score(y.iloc[te], p))
        model = _model().fit(Xd, y)
        x_today = row.fillna(0.0)
        prob = float(model.predict_proba(x_today)[0, 1])
        # explain: standardised value × coefficient = push toward "up" (+) or "down" (−)
        sc, lr = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
        z = (x_today.values[0] - sc.mean_) / np.where(sc.scale_ == 0, 1, sc.scale_)
        contrib = z * lr.coef_[0]
        drivers = []
        for j in np.argsort(-np.abs(contrib))[:5]:
            f = feats[j]
            sym = f.replace("ret_", "") if f.startswith("ret_") else None
            name = NAMES.get(sym, sym) if sym else ("Nifty 50 (yesterday)" if f == "nifty_ret1" else "Nifty 50 (5 days)")
            val = x_today.values[0][j]
            drivers.append({"input": name, "move_pct": round(float(val) * 100, 2), "push": round(float(contrib[j]), 3)})
        acc, base = float(np.mean(accs)), float(np.mean(bases))
        out["targets"][target] = {
            "available": True, "label": label, "prob_up": prob,
            "cv_accuracy": acc, "baseline_accuracy": base, "cv_auc": float(np.mean(aucs)) if aucs else None,
            "has_edge": acc - base > 0.02, "train_rows": int(len(d)),
            "base_rate_up": float(y.mean()), "drivers": drivers,
        }
        saved[target] = model
    if saved:
        joblib.dump({"models": saved, "features": feats, "trained_at": datetime.now().isoformat()}, MODEL_PATH)
    return out
