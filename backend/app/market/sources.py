"""Fetchers for the morning briefing. Every fetch is cached under data/market_cache/<date>/,
fails independently (one dead source never breaks the briefing), and reports its status.

Sources
  * Yahoo Finance chart API (indices, commodities, FX, yields; history for the outlook model)
  * RSS news: CNBC-TV18 (India), CNBC (world), Yahoo Finance (world)
  * NSE: event calendar, corporate actions, all-indices snapshot, equity list
  * NSE bhavcopy (already used by the watchlist sync): market breadth and top movers
"""
from __future__ import annotations

import email.utils
import hashlib
import io
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from ..config import DATA_DIR

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
CACHE_DIR = DATA_DIR / "market_cache"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")


class FetchError(RuntimeError):
    pass


class Http:
    """requests wrapper with a per-day disk cache, polite pacing and a test hook."""

    def __init__(self, fetcher: Callable[[str], bytes | None] | None = None, day: date | None = None,
                 pause: float = 0.4):
        self.fetcher = fetcher
        self.day = day or datetime.now(IST).date()
        self.pause = 0 if fetcher else pause
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        self._nse_warm = False
        self.status: dict[str, dict] = {}   # source -> {"ok": bool, "detail": str}

    def note(self, source: str, ok: bool, detail: str = ""):
        prev = self.status.get(source)
        if prev and prev["ok"] and not ok:
            return  # keep "ok" if any request for this source succeeded
        self.status[source] = {"ok": ok, "detail": detail}

    def get(self, url: str, *, max_age_h: float = 6, headers: dict | None = None, nse: bool = False) -> bytes:
        key = hashlib.sha1(url.encode()).hexdigest()[:20]
        folder = CACHE_DIR / self.day.isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / key
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age_h * 3600:
            return path.read_bytes()
        if self.fetcher:
            raw = self.fetcher(url)
            if raw is None:
                raise FetchError("HTTP 404")
        else:
            raw = self._net(url, headers or {}, nse)
        path.write_bytes(raw)
        return raw

    def _net(self, url: str, headers: dict, nse: bool) -> bytes:
        if nse and not self._nse_warm:
            try:  # NSE APIs want the cookies the home page sets
                self.s.get("https://www.nseindia.com/", timeout=15)
            except requests.RequestException:
                pass
            self._nse_warm = True
        last = ""
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=25, headers=headers)
            except requests.RequestException as e:
                last = type(e).__name__
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 200 and r.content:
                time.sleep(self.pause)
                return r.content
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403) and nse:
                self._nse_warm = False
            if r.status_code == 404:
                break
            time.sleep(2.0 * (attempt + 1))  # 429 / 5xx: back off
        raise FetchError(last or "no response")


# ------------------------------------------------------------------ Yahoo Finance

def yahoo_chart(http: Http, symbol: str, rng: str = "3mo", interval: str = "1d", max_age_h: float = 6) -> pd.DataFrame:
    """Daily OHLC for a Yahoo symbol. Index = trading date (exchange-local), columns open/high/low/close."""
    q = requests.utils.quote(symbol, safe="")
    last_err = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range={rng}&interval={interval}&includePrePost=false"
        try:
            data = json.loads(http.get(url, max_age_h=max_age_h))
            res = (data.get("chart") or {}).get("result") or []
            if not res:
                err = (data.get("chart") or {}).get("error") or {}
                raise FetchError(err.get("description") or "empty result")
            r = res[0]
            ts = r.get("timestamp") or []
            quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
            if not ts:
                raise FetchError("no data points")
            gmtoff = (r.get("meta") or {}).get("gmtoffset", 0) or 0
            idx = pd.to_datetime([t + gmtoff for t in ts], unit="s").normalize()
            df = pd.DataFrame({k: quote.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume")},
                              index=idx).apply(pd.to_numeric, errors="coerce")
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
            df.attrs["meta"] = r.get("meta") or {}
            return df
        except (FetchError, ValueError, KeyError) as e:
            last_err = e
    raise FetchError(f"{symbol}: {last_err}")


# ------------------------------------------------------------------ RSS

_TAG = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    t = html.unescape(_TAG.sub(" ", text or ""))
    return re.sub(r"\s+", " ", t).strip()


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(IST)


def parse_rss(raw: bytes) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, link, summary, published (IST datetime), publisher}]"""
    raw = raw.lstrip()
    root = ET.fromstring(raw)
    items = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1].lower()
        if tag not in ("item", "entry"):
            continue
        f = {c.tag.rsplit("}", 1)[-1].lower(): c for c in it}
        title = _clean(f["title"].text if "title" in f else "")
        if not title:
            continue
        link = ""
        if "link" in f:
            link = (f["link"].text or f["link"].attrib.get("href", "")).strip()
        summary = ""
        for k in ("description", "summary", "content"):
            if k in f and (f[k].text or "").strip():
                summary = _clean(f[k].text)
                break
        pub = None
        for k in ("pubdate", "published", "updated", "date"):
            if k in f:
                pub = _parse_date(f[k].text)
                if pub:
                    break
        publisher = _clean(f["source"].text) if "source" in f else ""
        items.append({"title": title, "link": link, "summary": summary[:600], "published": pub,
                      "publisher": publisher})
    return items


def fetch_news(http: Http, feeds, since_hours: float = 30) -> list[dict]:
    now = datetime.now(IST)
    out, seen = [], set()
    for key, source, region, url in feeds:
        try:
            items = parse_rss(http.get(url, max_age_h=1))
            http.note(source, True, f"{len(items)} stories")
        except Exception as e:  # noqa: BLE001
            http.note(source, False, str(e)[:120])
            log.warning("news feed %s failed: %s", key, e)
            continue
        for it in items:
            pub = it["published"]
            if pub and (now - pub).total_seconds() > since_hours * 3600:
                continue
            k = re.sub(r"\W+", "", it["title"].lower())[:90]
            if k in seen:
                continue
            seen.add(k)
            out.append({**it, "source": source, "region": region, "feed": key,
                        "published": pub.isoformat() if pub else None})
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out


# ------------------------------------------------------------------ NSE

def _nse_json(http: Http, url: str):
    raw = http.get(url, max_age_h=3, nse=True, headers={"Referer": "https://www.nseindia.com/", "Accept": "application/json"})
    head = raw[:200].lower()
    if b"<html" in head or b"<!doctype" in head:
        raise FetchError("NSE returned a web page instead of data (blocked or cookies missing)")
    return json.loads(raw)


def _d(v) -> str | None:
    if not v:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def nse_events(http: Http, start: date, days: int = 7) -> list[dict]:
    """Board meetings (results, dividends, fund raising…) and corporate actions (ex-dates)."""
    f, t = start.strftime("%d-%m-%Y"), (start + timedelta(days=days)).strftime("%d-%m-%Y")
    events = []
    try:
        cal = _nse_json(http, f"https://www.nseindia.com/api/event-calendar?index=equities&from_date={f}&to_date={t}")
        rows = cal if isinstance(cal, list) else cal.get("data", [])
        for r in rows:
            events.append({"date": _d(r.get("date")), "symbol": (r.get("symbol") or "").strip(),
                           "company": (r.get("company") or "").strip(), "type": "Board meeting",
                           "purpose": (r.get("purpose") or "").strip(),
                           "detail": _clean(r.get("bm_desc"))[:300]})
        http.note("NSE event calendar", True, f"{len(rows)} events")
    except Exception as e:  # noqa: BLE001
        http.note("NSE event calendar", False, str(e)[:120])
    try:
        ca = _nse_json(http, "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
                             f"&from_date={f}&to_date={t}")
        rows = ca if isinstance(ca, list) else ca.get("data", [])
        for r in rows:
            events.append({"date": _d(r.get("exDate")), "symbol": (r.get("symbol") or "").strip(),
                           "company": (r.get("comp") or "").strip(), "type": "Ex-date",
                           "purpose": (r.get("subject") or "").strip(),
                           "detail": f"Record date {r.get('recDate')}" if r.get("recDate") else ""})
        http.note("NSE corporate actions", True, f"{len(rows)} actions")
    except Exception as e:  # noqa: BLE001
        http.note("NSE corporate actions", False, str(e)[:120])
    events = [e for e in events if e["date"] and e["symbol"]]
    events.sort(key=lambda e: (e["date"], e["symbol"]))
    return events


def nse_all_indices(http: Http) -> dict[str, dict]:
    """Official NSE snapshot (last session) keyed by index name, e.g. 'NIFTY 50'."""
    data = _nse_json(http, "https://www.nseindia.com/api/allIndices")
    out = {}
    for r in data.get("data", []):
        name = (r.get("index") or r.get("indexSymbol") or "").strip().upper()
        if not name:
            continue

        def n(*keys):
            for k in keys:
                v = r.get(k)
                try:
                    return float(str(v).replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return None
        out[name] = {"name": (r.get("index") or name).strip(), "group": (r.get("key") or "").strip(),
                     "last": n("last"), "change_pct": n("percentChange"), "prev_close": n("previousClose"),
                     "open": n("open"), "high": n("high"), "low": n("low"),
                     "advances": n("advances"), "declines": n("declines"), "pe": n("pe"), "pb": n("pb"), "dy": n("dy"),
                     "year_high": n("yearHigh"), "year_low": n("yearLow"),
                     "change_30d": n("perChange30d"), "change_365d": n("perChange365d")}
    return out


def nse_equity_names(http: Http) -> dict[str, str]:
    """SYMBOL -> company name from NSE's master list (refreshed weekly)."""
    raw = http.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", max_age_h=24 * 7)
    df = pd.read_csv(io.BytesIO(raw), dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    return dict(zip(df["SYMBOL"].str.strip(), df["NAME OF COMPANY"].str.strip()))
