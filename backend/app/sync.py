"""Watchlist + bhavcopy sync engine + daily scheduler.

* Watchlist: symbols to track (stocks or indices), stored in data/watchlist.json.
* Sync: for every trading day after each symbol's last stored date, download that
  day's bhavcopy once, pull out the rows for all watchlist symbols, merge them into
  each symbol's history, then re-run the full analysis (indicators, ML, patterns,
  ChromaDB memory) for every symbol that received new data.
* Backfill: same mechanism, starting N days back, for symbols with no history yet.
* Scheduler: a background thread runs the sync Mon–Fri at AUTO_SYNC_TIME (IST) and
  once at startup to catch up on days missed while the computer was off.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .bhavcopy import BhavcopyClient, BhavcopyError, guess_kind, norm_symbol, pick_rows, weekdays
from .config import AUTO_SYNC, AUTO_SYNC_ON_START, AUTO_SYNC_TIME, RESULTS_DIR, WATCHLIST_FILE
from .data_loader import _history_path, clean_index, merge_history

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
PUBLISH_HOUR = 18  # bhavcopy for today is normally available after ~6 pm IST


def now_ist() -> datetime:
    return datetime.now(IST)


# ------------------------------------------------------------------ watchlist

_wl_lock = threading.Lock()


def load_watchlist() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        return json.loads(WATCHLIST_FILE.read_text())
    except Exception:  # noqa: BLE001
        return []


def save_watchlist(items: list[dict]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(items, indent=2))


def add_symbol(symbol: str, kind: str | None = None) -> dict:
    sym = norm_symbol(symbol)
    if not sym:
        raise ValueError("Empty symbol")
    kind = kind if kind in ("equity", "index") else guess_kind(sym)
    with _wl_lock:
        items = load_watchlist()
        for it in items:
            if it["symbol"] == sym:
                it["kind"] = kind
                save_watchlist(items)
                return it
        it = {"symbol": sym, "kind": kind, "added_at": now_ist().isoformat(timespec="seconds")}
        items.append(it)
        save_watchlist(items)
        return it


def remove_symbol(symbol: str) -> bool:
    sym = norm_symbol(symbol)
    with _wl_lock:
        items = load_watchlist()
        keep = [i for i in items if i["symbol"] != sym]
        save_watchlist(keep)
        return len(keep) != len(items)


def last_stored_date(symbol: str) -> date | None:
    path = _history_path(symbol, False)
    if not path.exists():
        return None
    try:
        idx = pd.read_csv(path, usecols=[0], index_col=0, parse_dates=True).index
        return idx.max().date() if len(idx) else None
    except Exception:  # noqa: BLE001
        return None


def stored_rows(symbol: str) -> int:
    path = _history_path(symbol, False)
    if not path.exists():
        return 0
    with open(path) as f:
        return max(sum(1 for _ in f) - 1, 0)


def watchlist_status() -> list[dict]:
    out = []
    for it in load_watchlist():
        sym = it["symbol"]
        row = {**it, "last_date": None, "rows": stored_rows(sym), "verdicts": None, "close": None,
               "change_pct": None, "pattern": None, "analysed_at": None}
        ld = last_stored_date(sym)
        row["last_date"] = ld.isoformat() if ld else None
        res = RESULTS_DIR / f"{sym}.json"
        if res.exists():
            try:
                r = json.loads(res.read_text())
                row["verdicts"] = {k: v["combined"]["verdict"] for k, v in r["timeframes"].items()}
                row["close"] = r["meta"]["close"]
                row["change_pct"] = r["meta"]["change_pct"]
                pred = (r.get("patterns") or {}).get("prediction") or {}
                row["pattern"] = pred.get("text")
                row["analysed_at"] = r.get("analysed_at")
            except Exception:  # noqa: BLE001
                pass
        out.append(row)
    return out


# ------------------------------------------------------------------ sync job

class SyncJob:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "started_at": None, "finished_at": None, "progress": None,
                      "log": [], "results": {}, "error": None, "trigger": None}

    def _log(self, msg: str):
        log.info("sync: %s", msg)
        self.state["log"].append(f"{now_ist().strftime('%H:%M:%S')}  {msg}")
        self.state["log"] = self.state["log"][-200:]

    def status(self) -> dict:
        return {**self.state, "log": list(self.state["log"])}

    def start(self, analyse, symbols: list[str] | None = None, backfill_days: int = 365,
              trigger: str = "manual", client: BhavcopyClient | None = None, wait: bool = False) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update({"running": True, "started_at": now_ist().isoformat(timespec="seconds"),
                               "finished_at": None, "progress": None, "log": [], "results": {},
                               "error": None, "trigger": trigger})
        t = threading.Thread(target=self._run, args=(analyse, symbols, backfill_days, client), daemon=True)
        t.start()
        if wait:
            t.join()
        return True

    def _run(self, analyse, symbols, backfill_days, client):
        try:
            self._sync(analyse, symbols, backfill_days, client or BhavcopyClient())
        except Exception as e:  # noqa: BLE001
            log.exception("sync failed")
            self.state["error"] = str(e)
            self._log(f"ERROR: {e}")
        finally:
            self.state["running"] = False
            self.state["finished_at"] = now_ist().isoformat(timespec="seconds")

    def _sync(self, analyse, symbols, backfill_days, client: BhavcopyClient):
        items = load_watchlist()
        if symbols:
            wanted = {norm_symbol(s) for s in symbols}
            items = [i for i in items if i["symbol"] in wanted]
        if not items:
            self._log("Watchlist is empty — add symbols first.")
            return

        now = now_ist()
        end = now.date() if now.hour >= PUBLISH_HOUR else now.date() - timedelta(days=1)
        starts: dict[str, date] = {}
        for it in items:
            last = last_stored_date(it["symbol"])
            starts[it["symbol"]] = (last + timedelta(days=1)) if last else end - timedelta(days=backfill_days)
            self._log(f"{it['symbol']}: " + (f"have data to {last}, fetching from {starts[it['symbol']]}"
                                              if last else f"no history — backfilling {backfill_days} days"))
        first = min(starts.values())
        days = list(weekdays(first, end))
        if not days:
            self._log(f"Already up to date (latest expected session: {end}).")
            return

        kinds = {it["symbol"]: it["kind"] for it in items}
        need_eq = any(k == "equity" for k in kinds.values())
        need_ix = any(k == "index" for k in kinds.values())
        collected: dict[str, list[pd.DataFrame]] = {s: [] for s in kinds}
        missing_days, found_days = [], 0
        self._log(f"Checking {len(days)} weekday(s) from {days[0]} to {days[-1]}")
        for n, d in enumerate(days, 1):
            self.state["progress"] = {"done": n, "total": len(days), "date": d.isoformat()}
            eq = client.equity_day(d) if need_eq and any(
                kinds[s] == "equity" and starts[s] <= d for s in kinds) else None
            ix = client.index_day(d) if need_ix and any(
                kinds[s] == "index" and starts[s] <= d for s in kinds) else None
            if eq is None and ix is None:
                missing_days.append(d)
                continue
            found_days += 1
            for sym, kind in kinds.items():
                if d < starts[sym]:
                    continue
                src = eq if kind == "equity" else ix
                if src is None:
                    continue
                rows = pick_rows(src, sym)
                if not rows.empty:
                    collected[sym].append(rows)

        if missing_days:
            recent = [x for x in missing_days if (end - x).days <= 1]
            note = " (today's file may not be published yet)" if recent else ""
            self._log(f"No bhavcopy for {len(missing_days)} weekday(s) — holidays or unpublished{note}")
        self._log(f"Downloaded/used {found_days} trading day file(s); {client.downloads} new download(s)")
        if client.mismatched:
            ex = ", ".join(f"{d} had {got[0]}" for _, d, got in client.mismatched[:3])
            self._log(f"Ignored {len(client.mismatched)} file(s) whose contents were for a different date ({ex}) — "
                      "they'll be retried next sync")

        for sym, parts in collected.items():
            res = {"new_rows": 0, "analysed": False}
            if not parts:
                if starts[sym] > end:
                    found = f"up to date (latest session {end})"
                elif found_days:
                    found = "not found in bhavcopy — check the symbol (NSE ticker, e.g. RELIANCE, M&M, BAJAJ-AUTO)"
                else:
                    found = "no new sessions published yet"
                self._log(f"{sym}: {found}")
                res["message"] = found
                self.state["results"][sym] = res
                continue
            new = pd.concat(parts).set_index("date")
            dupes = int(new.index.duplicated().sum())
            if dupes:
                self._log(f"{sym}: {dupes} repeated trade date(s) in downloaded files — kept one row per date")
            new = clean_index(new)
            cols = ["open", "high", "low", "close", "volume"] + (["vwap_src"] if "vwap_src" in new else [])
            merged, total = analyse.merge(new[cols], sym)
            res.update({"new_rows": len(new), "total_rows": total, "last_date": new.index[-1].date().isoformat()})
            self._log(f"{sym}: +{len(new)} session(s), {total} total, latest {res['last_date']}")
            if total < 30:
                res["message"] = "need at least 30 sessions to analyse"
                self.state["results"][sym] = res
                continue
            try:
                out = analyse.run(merged, {"symbol": sym, "is_intraday": False, "rows_uploaded": len(new),
                                           "rows_total": total, "source": "bhavcopy"})
                v = {k: t["combined"]["verdict"] for k, t in out["timeframes"].items()}
                res.update({"analysed": True, "verdicts": v})
                self._log(f"{sym}: analysed — day {v['day_trading']}, short {v['short_term']}, long {v['long_term']}")
            except Exception as e:  # noqa: BLE001
                log.exception("analysis failed for %s", sym)
                res["message"] = f"analysis failed: {e}"
                self._log(f"{sym}: analysis failed: {e}")
            self.state["results"][sym] = res
        self._log("Sync finished.")


JOB = SyncJob()


# ------------------------------------------------------------------ scheduler

def _next_run(after: datetime) -> datetime:
    hh, mm = (int(x) for x in AUTO_SYNC_TIME.split(":"))
    cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= after:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:
        cand += timedelta(days=1)
    return cand


def start_scheduler(analyse) -> None:
    if not AUTO_SYNC:
        log.info("auto-sync disabled (AUTO_SYNC=false)")
        return

    def loop():
        if AUTO_SYNC_ON_START and load_watchlist():
            time.sleep(5)
            JOB.start(analyse, trigger="startup catch-up")
        while True:
            nxt = _next_run(now_ist())
            log.info("next scheduled bhavcopy sync: %s", nxt.strftime("%a %d %b %H:%M IST"))
            while now_ist() < nxt:
                time.sleep(min(60, max(1, (nxt - now_ist()).total_seconds())))
            if load_watchlist():
                JOB.start(analyse, trigger="scheduled")

    threading.Thread(target=loop, name="bhavcopy-scheduler", daemon=True).start()


def scheduler_info() -> dict:
    return {"enabled": AUTO_SYNC, "time_ist": AUTO_SYNC_TIME,
            "next_run": _next_run(now_ist()).isoformat(timespec="minutes") if AUTO_SYNC else None}


class Analyse:
    """Adapter so the sync engine can call the API's merge + analysis without importing main."""

    def __init__(self, run_analysis, lock):
        self._run, self._lock = run_analysis, lock

    def merge(self, df, sym):
        with self._lock:
            return merge_history(df, sym, False)

    def run(self, df, meta):
        return self._run(df, meta)


__all__ = ["JOB", "Analyse", "BhavcopyError", "add_symbol", "remove_symbol", "watchlist_status",
           "start_scheduler", "scheduler_info", "load_watchlist"]
