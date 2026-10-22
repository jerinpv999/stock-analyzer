"""FastAPI app: upload an NSE CSV -> indicators + ML + memory-aware analysis."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import analysis as A
from .config import CHART_BARS, CORS_ORIGINS, DATA_DIR, RESULTS_DIR
from .data_loader import (DataError, _history_path, clean_index, history_is_intraday, load_csv,
                          merge_history, read_history)
from .indicators import add_all
from .memory import AnalysisMemory, evaluate_past_calls
from .model import HORIZONS, train_and_predict
from .patterns import PATTERN_HORIZON, PatternModel, detect, pattern_stats, recent_occurrences

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nse")

app = FastAPI(title="NSE Stock Analyzer", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

_memory: AnalysisMemory | None = None
ANALYSIS_LOCK = threading.RLock()  # uploads and the background sync share model/history files


def safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9&_-]", "_", sym)


_memory_lock = threading.Lock()


def memory() -> AnalysisMemory:
    global _memory
    if _memory is None:
        with _memory_lock:  # startup warm-up and the first request must not both build it
            if _memory is None:
                _memory = AnalysisMemory()
    return _memory


def clean(o):
    """Make numpy/pandas values JSON-safe (NaN/inf -> None)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    return o


CHART_COLS = ["open", "high", "low", "close", "volume", "sma20", "sma50", "sma200", "ema9", "ema21",
              "bb_upper", "bb_mid", "bb_lower", "supertrend", "st_dir", "vwap", "rsi", "macd", "macd_signal",
              "macd_hist", "stoch_k", "stoch_d", "adx", "plus_di", "minus_di", "obv"]


def chart_payload(df: pd.DataFrame, intraday: bool) -> list[dict]:
    d = df.tail(CHART_BARS)
    # naive local timestamps treated as UTC so charts show IST clock times
    ts = (d.index.astype("int64") // 10**9).tolist()
    recs = d[CHART_COLS].round(4).replace([np.inf, -np.inf], np.nan).astype(object).where(d[CHART_COLS].notna(), None)
    out = recs.to_dict(orient="records")
    fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    for row, t, idx in zip(out, ts, d.index):
        row["ts"] = int(t)
        row["date"] = idx.strftime(fmt)
    return out


def build_summary(sym: str, last_date: str, close: float, tfs: dict, ml: dict, lv: dict, latest: pd.Series) -> str:
    shown = last_date[:10] if last_date[11:16] == "00:00" else last_date[:16].replace("T", " ")
    parts = [f"{sym} technical analysis on data up to {shown}. Close {close:.2f}."]
    for key, label in (("day_trading", "Day trading"), ("short_term", "Short term"), ("long_term", "Long term")):
        t = tfs[key]
        m = ml[key]
        mltxt = f", model P(up {m['horizon_label']}) {m['prob_up']:.2f}" if m.get("available") else ""
        drivers = "; ".join(s["note"] for s in sorted(t["signals"], key=lambda s: -abs(s["bias"]))[:3])
        parts.append(f"{label}: {t['combined']['verdict']} (score {t['combined']['score']:+.0f}{mltxt}). {drivers}.")
    rsi = latest.get("rsi")
    parts.append(
        f"RSI {rsi:.0f}." if rsi is not None and not pd.isna(rsi) else ""
    )
    if lv["supports"]:
        parts.append(f"Support {lv['supports'][0]['price']}.")
    if lv["resistances"]:
        parts.append(f"Resistance {lv['resistances'][0]['price']}.")
    if lv["patterns"]:
        parts.append("Patterns: " + ", ".join(p["name"] for p in lv["patterns"]) + ".")
    return " ".join(p for p in parts if p).strip()


def compare_with_previous(prev: dict | None, close: float, tfs: dict) -> dict | None:
    if not prev:
        return None
    changes = []
    for key, label in (("day_trading", "Day trading"), ("short_term", "Short term"), ("long_term", "Long term")):
        old = prev.get(f"{key}_verdict")
        new = tfs[key]["combined"]["verdict"]
        if old and old != new:
            changes.append(f"{label} view changed {old} → {new}")
    pc = prev.get("close")
    return {
        "previous_id": prev["id"],
        "previous_created_at": prev.get("created_at"),
        "previous_last_date": prev.get("last_date"),
        "previous_close": pc,
        "price_change_pct": round((close / pc - 1) * 100, 2) if pc else None,
        "verdict_changes": changes or ["No change in timeframe verdicts"],
        "previous_summary": prev.get("summary"),
    }


@app.get("/api/health")
def health():
    """Answers instantly — loading the ChromaDB embedding model (first start downloads it) happens in the background."""
    host_dir = os.getenv("NSE_DATA_DIR_ON_HOST")  # set by docker-compose: the real folder on the host
    out = {"status": "ok", "data_dir": host_dir or str(DATA_DIR), "in_docker": bool(host_dir),
           "memory_ready": _memory is not None}
    if _memory is not None:
        out.update(embedding_backend=_memory.backend, stored_analyses=_memory.col.count())
    return out


@app.on_event("startup")
def _warm_memory():
    def warm():
        try:
            memory()
        except Exception:  # noqa: BLE001
            log.exception("ChromaDB memory failed to start")
    threading.Thread(target=warm, name="memory-warmup", daemon=True).start()


@app.post("/api/analyze")
def analyze(file: UploadFile = File(...), symbol: str | None = Form(None), merge: str | None = Form(None),
            ephemeral: str | None = Form(None)):
    # parsed by hand: some FastAPI versions turn a missing bool form field into False instead of the default
    merge = (merge or "true").strip().lower() not in ("false", "0", "no", "off")
    # ephemeral = demo/sample run: analyse but save nothing (no history, memory or results)
    ephemeral = (ephemeral or "").strip().lower() in ("true", "1", "yes")
    if ephemeral:
        merge = False
    raw = file.file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 50MB).")
    try:
        df, meta = load_csv(raw, file.filename, (symbol or "").strip() or None)
    except DataError as e:
        raise HTTPException(400, str(e)) from e

    sym, intraday = meta["symbol"], meta["is_intraday"]
    if merge:
        if len(df) < 3:
            # too few rows to infer the bar interval: trust what is already stored for this symbol
            intraday = meta["is_intraday"] = history_is_intraday(sym)
        with ANALYSIS_LOCK:
            df, meta["rows_total"] = merge_history(df, sym, intraday)
    else:
        meta["rows_total"] = len(df)
    if len(df) < 30:
        raise HTTPException(
            400,
            f"Only {len(df)} bars available for {sym}. Upload at least 30 sessions of history first "
            "(1 year recommended); after that, daily uploads of a single day are merged automatically.",
        )
    meta["ephemeral"] = ephemeral
    return run_analysis(df, meta)


def run_analysis(df: pd.DataFrame, meta: dict) -> dict:
    """Full pipeline on a merged price history: indicators, rules, ML, patterns, memory.
    Shared by CSV uploads and the bhavcopy auto-sync."""
    with ANALYSIS_LOCK:
        return _run_analysis(df, meta)


def _run_analysis(df: pd.DataFrame, meta: dict) -> dict:
    sym, intraday = meta["symbol"], meta["is_intraday"]
    meta.setdefault("rows_total", len(df))
    meta.setdefault("rows_uploaded", len(df))
    df = clean_index(df)  # defensive: indicators and patterns assume unique, sorted dates
    meta["first_date"] = df.index[0].isoformat()
    ind = add_all(df, intraday)
    latest = ind.iloc[-1]
    close = float(latest["close"])
    prev_close = float(ind["close"].iloc[-2])

    levels = A.compute_levels(ind, intraday)
    tfs = {
        "day_trading": A.day_trading(ind, levels),
        "short_term": A.short_term(ind, levels),
        "long_term": A.long_term(ind, levels, intraday),
    }
    ml = {}
    for key in HORIZONS:
        try:
            ml[key] = train_and_predict(ind, sym, key, intraday)
        except Exception as e:  # noqa: BLE001
            log.exception("model %s failed", key)
            ml[key] = {"available": False, "reason": f"Model error: {e}"}
        tfs[key]["ml"] = ml[key]
        tfs[key]["combined"] = A.combine(tfs[key]["score"], ml[key])

    # ---- candlestick patterns: detection, per-stock stats, prediction model
    pats = detect(ind)
    pstats = pattern_stats(ind, pats)
    try:
        pattern = PatternModel(add_all).run(sym, ind, pats, pstats)
    except Exception as e:  # noqa: BLE001
        log.exception("pattern model failed")
        pattern = {"today": [], "prediction": None, "model": {"available": False, "reason": f"Pattern model error: {e}"}}
    pattern["stats"] = pstats
    occ = recent_occurrences(ind, pats, CHART_BARS)
    fmt_d = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    for o in occ:
        o["date"] = o["ts"].strftime(fmt_d)
        o["ts"] = int(o["ts"].value // 10**9)
    pattern["occurrences"] = occ
    pattern["horizon_sessions"] = PATTERN_HORIZON

    last_date = ind.index[-1].isoformat()
    summary = build_summary(sym, last_date, close, tfs, ml, levels, latest)
    if pattern.get("prediction") and pattern["prediction"].get("text"):
        summary += " Pattern view: " + pattern["prediction"]["text"]

    # ---- memory: recall before storing the new one
    mem = memory()
    past = mem.history(sym, limit=200)
    previous = past[0] if past else None
    track = evaluate_past_calls(past, ind) if past else None
    similar_same = mem.similar(summary, symbol=sym, k=3)
    similar_other = mem.similar(summary, symbol=sym, k=3, exclude_symbol=True)

    store_meta = {
        "symbol": sym, "created_at": datetime.now().isoformat(timespec="seconds"), "last_date": last_date,
        "close": close, "is_intraday": intraday, "rows": meta["rows_total"],
        "rsi": latest.get("rsi"), "atr": latest.get("atr"),
    }
    for key in HORIZONS:
        store_meta[f"{key}_verdict"] = tfs[key]["combined"]["verdict"]
        store_meta[f"{key}_score"] = tfs[key]["combined"]["score"]
        if ml[key].get("available"):
            store_meta[f"{key}_prob_up"] = ml[key]["prob_up"]
    pred = pattern.get("prediction") or {}
    if pred.get("prob_up") is not None:
        store_meta["pattern_direction"] = pred["direction"]
        store_meta["pattern_prob_up"] = pred["prob_up"]
        store_meta["patterns_today"] = ", ".join(t["name"] for t in pattern["today"])
    analysis_id = None if meta.get("ephemeral") else mem.store(summary, store_meta)

    resp = {
        "analysis_id": analysis_id,
        "analysed_at": datetime.now().isoformat(timespec="seconds"),
        "meta": {**meta, "last_date": last_date, "close": close,
                 "change_pct": (close / prev_close - 1) * 100, "embedding_backend": mem.backend},
        "summary": summary,
        "timeframes": tfs,
        "levels": levels,
        "patterns": pattern,
        "latest": {k: latest.get(k) for k in ("rsi", "macd", "macd_signal", "adx", "atr", "stoch_k",
                                              "bb_pctb", "sma50", "sma200", "ema21", "vwap", "supertrend")},
        "memory": {
            "previous": compare_with_previous(previous, close, tfs),
            "track_record": track,
            "similar_same_symbol": similar_same,
            "similar_other_symbols": similar_other,
            "total_past_analyses": len(past),
        },
        "chart": chart_payload(ind, intraday),
        "disclaimer": "For educational purposes only — not investment advice or a recommendation. "
                      "Not from a SEBI-registered investment adviser or research analyst. "
                      "Automated analysis can be wrong; consult a SEBI-registered adviser before investing.",
    }
    out = clean(resp)
    try:
        if not meta.get("ephemeral"):
            (RESULTS_DIR / f"{safe_name(sym)}.json").write_text(json.dumps(out))
    except Exception as e:  # noqa: BLE001
        log.warning("could not save result for %s: %s", sym, e)
    return out


@app.get("/api/history/{symbol}")
def history(symbol: str, limit: int = 50):
    return clean(memory().history(symbol.upper(), limit))


@app.get("/api/symbols")
def symbols():
    return memory().symbols()


@app.get("/api/search")
def search(q: str, symbol: str | None = None, k: int = 5):
    return clean(memory().similar(q, symbol=symbol.upper() if symbol else None, k=k))


@app.delete("/api/history/{symbol}")
def delete_history(symbol: str):
    return {"deleted": memory().delete_symbol(symbol.upper())}


# ---------------------------------------------------------------- bhavcopy auto-sync

from . import sync as S  # noqa: E402

ANALYSE = S.Analyse(run_analysis, ANALYSIS_LOCK)


@app.on_event("startup")
def _start_scheduler():
    S.start_scheduler(ANALYSE)


@app.get("/api/watchlist")
def watchlist():
    return clean({"items": S.watchlist_status(), "scheduler": S.scheduler_info(), "sync": S.JOB.status()})


@app.post("/api/watchlist")
def watchlist_add(payload: dict = Body(...)):
    syms = payload.get("symbols") or [payload.get("symbol", "")]
    added = []
    for raw in syms:
        for part in str(raw).replace(";", ",").split(","):
            if part.strip():
                try:
                    added.append(S.add_symbol(part, payload.get("kind")))
                except ValueError as e:
                    raise HTTPException(400, str(e)) from e
    if not added:
        raise HTTPException(400, "No symbol given.")
    started = False
    if payload.get("sync", True):
        started = S.JOB.start(ANALYSE, symbols=[a["symbol"] for a in added],
                              backfill_days=int(payload.get("backfill_days", 365)), trigger="added to watchlist")
    return {"added": added, "sync_started": started}


@app.delete("/api/watchlist/{symbol}")
def watchlist_remove(symbol: str):
    return {"removed": S.remove_symbol(symbol)}


@app.post("/api/sync")
def sync_now(payload: dict = Body(default={})):
    started = S.JOB.start(ANALYSE, symbols=payload.get("symbols"),
                          backfill_days=int(payload.get("backfill_days", 365)), trigger="manual")
    if not started:
        raise HTTPException(409, "A sync is already running.")
    return {"started": True}


@app.get("/api/sync/status")
def sync_status():
    return S.JOB.status()


@app.post("/api/analyze-stored/{symbol}")
def analyze_stored(symbol: str):
    """Re-run the full analysis on price history already stored for a symbol (from sync or uploads)."""
    sym = symbol.strip().upper()
    for intraday in (False, True):
        path = _history_path(sym, intraday)
        if path.exists():
            break
    else:
        raise HTTPException(404, f"No stored data for {sym}. Sync it from the Watchlist or upload a CSV first.")
    with ANALYSIS_LOCK:
        df = read_history(path)
    if len(df) < 30:
        raise HTTPException(400, f"Only {len(df)} sessions stored for {sym}; need at least 30.")
    return run_analysis(df, {"symbol": sym, "is_intraday": intraday, "rows_uploaded": 0,
                             "rows_total": len(df), "source": "stored"})


@app.get("/api/results/{symbol}")
def latest_result(symbol: str):
    path = RESULTS_DIR / f"{safe_name(symbol.upper())}.json"
    if not path.exists():
        raise HTTPException(404, f"No saved analysis for {symbol.upper()} yet.")
    return json.loads(path.read_text())


# ---------------------------------------------------------------- morning market briefing

from .market import briefing as MB  # noqa: E402
from .market import scheduler as MS  # noqa: E402


@app.on_event("startup")
def _start_briefing_scheduler():
    MS.start()


def _slim(b: dict | None) -> dict | None:
    """Drop the raw news list (kept on disk for the weekly recap) from API responses."""
    if not b:
        return b
    if b.get("kind") == "daily":
        b = {**b, "news": {k: v for k, v in b["news"].items() if k != "all_items"}}
    return clean(b)


@app.get("/api/briefing/latest")
def briefing_latest():
    return {"daily": _slim(MB.load("daily")), "weekly": _slim(MB.load("weekly")),
            "status": MS.JOB.status(), "schedule": MS.info()}


@app.get("/api/briefing/list")
def briefing_list():
    return {"daily": MB.list_saved("daily"), "weekly": MB.list_saved("weekly")}


@app.get("/api/briefing/daily/{day}")
def briefing_daily(day: str):
    b = MB.load("daily", day)
    if not b:
        raise HTTPException(404, f"No daily briefing for {day}.")
    return _slim(b)


@app.get("/api/briefing/weekly/{monday}")
def briefing_weekly(monday: str):
    b = MB.load("weekly", monday)
    if not b:
        raise HTTPException(404, f"No weekly recap for the week of {monday}.")
    return _slim(b)


@app.post("/api/briefing/refresh")
def briefing_refresh(payload: dict = Body(default={})):
    kind = payload.get("kind", "daily")
    if kind not in ("daily", "weekly"):
        raise HTTPException(400, "kind must be 'daily' or 'weekly'")
    if not MS.JOB.start(kind, trigger="manual"):
        raise HTTPException(409, "A briefing is already being built.")
    return {"started": True, "kind": kind}


@app.get("/api/briefing/status")
def briefing_status():
    return {"status": MS.JOB.status(), "schedule": MS.info()}
