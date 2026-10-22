"""Runs the briefing automatically.

  * Daily briefing: Mon–Fri at BRIEFING_TIME (default 08:15 IST, ready before 08:30)
  * Weekly recap:   Saturday at WEEKLY_TIME (default 09:00 IST)
  * On startup:     builds whatever is missing (today's briefing after 08:15, this week's recap at the weekend)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from . import briefing as B
from .sources import IST

log = logging.getLogger(__name__)
AUTO = os.getenv("AUTO_BRIEFING", "true").lower() in ("1", "true", "yes")
DAILY_AT = os.getenv("BRIEFING_TIME", "08:15")
WEEKLY_AT = os.getenv("WEEKLY_TIME", "09:00")


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "kind": None, "started_at": None, "finished_at": None,
                      "step": None, "log": [], "error": None, "trigger": None}

    def _say(self, msg):
        self.state["step"] = msg
        self.state["log"] = (self.state["log"] + [f"{datetime.now(IST):%H:%M:%S}  {msg}"])[-60:]

    def status(self):
        return {**self.state, "log": list(self.state["log"])}

    def start(self, kind: str, trigger: str = "manual", wait: bool = False, **kw) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update({"running": True, "kind": kind, "started_at": datetime.now(IST).isoformat(timespec="seconds"),
                               "finished_at": None, "log": [], "error": None, "trigger": trigger, "step": "starting"})
        t = threading.Thread(target=self._run, args=(kind, kw), daemon=True)
        t.start()
        if wait:
            t.join()
        return True

    def _run(self, kind, kw):
        try:
            (B.build_daily if kind == "daily" else B.build_weekly)(log_fn=self._say, **kw)
        except Exception as e:  # noqa: BLE001
            log.exception("briefing failed")
            self.state["error"] = str(e)
            self._say(f"ERROR: {e}")
        finally:
            self.state["running"] = False
            self.state["finished_at"] = datetime.now(IST).isoformat(timespec="seconds")


JOB = Job()


def _at(day: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def next_runs(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    d = _at(now, DAILY_AT)
    while d <= now or d.weekday() >= 5:
        d = _at(d + timedelta(days=1), DAILY_AT)
    w = _at(now, WEEKLY_AT)
    while w <= now or w.weekday() != 5:
        w = _at(w + timedelta(days=1), WEEKLY_AT)
    return {"daily": d.isoformat(timespec="minutes"), "weekly": w.isoformat(timespec="minutes")}


def info() -> dict:
    return {"enabled": AUTO, "daily_time": DAILY_AT, "weekly_time": WEEKLY_AT, **(next_runs() if AUTO else {})}


def _missing_now(now: datetime) -> str | None:
    if now.weekday() < 5 and now >= _at(now, DAILY_AT) and not (B.DAILY_DIR / f"{now.date()}.json").exists():
        return "daily"
    if now.weekday() >= 5 or (now.weekday() == 4 and now.hour >= 18):
        mon, _ = B.week_bounds(now.date())
        if not (B.WEEKLY_DIR / f"{mon}.json").exists():
            return "weekly"
    return None


def start() -> None:
    if not AUTO:
        log.info("auto briefing disabled (AUTO_BRIEFING=false)")
        return

    def loop():
        time.sleep(8)
        kind = _missing_now(datetime.now(IST))
        if kind:
            JOB.start(kind, trigger="startup catch-up")
        while True:
            n = next_runs()
            target = min(datetime.fromisoformat(n["daily"]), datetime.fromisoformat(n["weekly"]))
            kind = "daily" if target == datetime.fromisoformat(n["daily"]) else "weekly"
            log.info("next %s briefing: %s", kind, target.strftime("%a %d %b %H:%M IST"))
            while datetime.now(IST) < target:
                time.sleep(min(60, max(1, (target - datetime.now(IST)).total_seconds())))
            for _ in range(30):  # wait for a running job (e.g. a manual refresh) to finish
                if JOB.start(kind, trigger="scheduled"):
                    break
                time.sleep(20)

    threading.Thread(target=loop, name="briefing-scheduler", daemon=True).start()
