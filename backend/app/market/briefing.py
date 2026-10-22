"""Builds the daily morning briefing (ready before 08:30 IST) and the weekly recap.

Saved as JSON in <data>/briefings/daily/YYYY-MM-DD.json and <data>/briefings/weekly/YYYY-MM-DD.json
(weekly files are named after the week's Monday).
"""
from __future__ import annotations

import io
import json
import logging
import shutil
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from ..bhavcopy import BhavcopyClient
from ..config import DATA_DIR
from . import nlp
from .outlook import load_history, train_and_predict
from .sources import CACHE_DIR, IST, FetchError, Http, fetch_news, nse_all_indices, nse_equity_names, nse_events, yahoo_chart
from .universe import CORE_ALIASES, GLOBAL, INDIA, NEWS_FEEDS
from . import participants as PT

log = logging.getLogger(__name__)
DAILY_DIR = DATA_DIR / "briefings" / "daily"
WEEKLY_DIR = DATA_DIR / "briefings" / "weekly"
for _d in (DAILY_DIR, WEEKLY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MIN_TURNOVER = 25e7  # ₹25 crore — filters illiquid stocks out of top gainers/losers


def _f(v, d=2):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)


def _quote(df: pd.DataFrame, today: date) -> dict:
    df = df.dropna(subset=["close"])
    last, prev = df.iloc[-1], (df.iloc[-2] if len(df) > 1 else df.iloc[-1])
    d = df.index[-1].date()
    return {"last": _f(last["close"], 4), "prev_close": _f(prev["close"], 4),
            "change_pct": _f((last["close"] / prev["close"] - 1) * 100, 2) if prev["close"] else None,
            "date": d.isoformat(), "stale": (today - d).days > 4,
            "spark": [_f(x, 4) for x in df["close"].tail(22).tolist()]}


def _watchlist() -> set[str]:
    try:
        from ..sync import load_watchlist
        return {i["symbol"] for i in load_watchlist()}
    except Exception:  # noqa: BLE001
        return set()


# ------------------------------------------------------------------ sections

def global_section(http: Http, today: date) -> list[dict]:
    rows, ok = [], 0
    for sym, name, group, kind in GLOBAL:
        row = {"symbol": sym, "name": name, "group": group, "kind": kind}
        try:
            row.update(_quote(yahoo_chart(http, sym, "1mo", max_age_h=2), today))
            ok += 1
        except FetchError as e:
            row["error"] = str(e)[:80]
        rows.append(row)
    http.note("Yahoo Finance quotes", ok > 0, f"{ok}/{len(GLOBAL)} instruments")
    return rows


def india_section(http: Http, today: date) -> dict:
    nse = {}
    try:
        nse = nse_all_indices(http)
        http.note("NSE indices", True, f"{len(nse)} indices")
    except Exception as e:  # noqa: BLE001
        http.note("NSE indices", False, str(e)[:120])
    rows = []
    for ysym, name, nse_name, group in INDIA:
        row = {"symbol": ysym, "name": name, "group": group, "source": None}
        try:
            row.update(_quote(yahoo_chart(http, ysym, "1mo", max_age_h=2), today))
            row["source"] = "Yahoo Finance"
        except FetchError as e:
            row["error"] = str(e)[:80]
        n = nse.get((nse_name or "").upper())
        if n and n.get("last"):
            row.update({"last": n["last"], "change_pct": _f(n["change_pct"]), "source": "NSE",
                        "advances": n.get("advances"), "declines": n.get("declines"), "pe": n.get("pe"),
                        "year_high": n.get("year_high"), "year_low": n.get("year_low")})
            row.pop("error", None)
        rows.append(row)
    client = getattr(http, "bhav", None)
    every, src = all_indices(nse, today, client)
    http.note("NSE all-index summary", bool(every), f"{len(every)} indices · {src}")
    return {"indices": rows, "all_indices": every, "all_indices_source": src, **breadth(today, client)}


# ------------------------------------------------------------------ all NSE indices

GROUPS = {"BROAD MARKET INDICES": "Broad market", "SECTORAL INDICES": "Sectoral", "THEMATIC INDICES": "Thematic",
          "STRATEGY INDICES": "Strategy", "FIXED INCOME INDICES": "Fixed income", "INDICES ELIGIBLE IN DERIVATIVES": "Broad market"}
GROUP_ORDER = ["Broad market", "Sectoral", "Thematic", "Strategy", "Fixed income", "Other"]
_SECTOR_WORDS = ("BANK", " IT", "AUTO", "FMCG", "PHARMA", "METAL", "REALTY", "ENERGY", "MEDIA", "FINANCIAL", "OIL & GAS",
                 "CONSUMER DURABLES", "HEALTHCARE", "CHEMICALS")
_BROAD = ("NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY 500", "MIDCAP", "SMALLCAP", "MICROCAP",
          "LARGEMIDCAP", "TOTAL MARKET", "INDIA VIX")


def index_group(name: str, nse_key: str = "") -> str:
    if nse_key and nse_key.upper() in GROUPS:
        return GROUPS[nse_key.upper()]
    n = f" {name.upper()} "
    if any(k in n for k in ("G-SEC", "GSEC", "BOND", "SDL", "T-BILL", "GILT", "1D RATE", "CPSE BOND")):
        return "Fixed income"
    if any(k in n for k in ("ALPHA", "LOW VOL", "QUALITY", "VALUE", "MOMENTUM", "EQUAL WEIGHT", "DIVIDEND OPP", "GROWTH SECT")):
        return "Strategy"
    if any(f" {k.strip()} " in n or n.strip() == k.strip() for k in _SECTOR_WORDS) and "MIDCAP" not in n and "SMALLCAP" not in n:
        return "Sectoral"
    if any(n.strip() == k or n.strip().startswith(k) for k in _BROAD):
        return "Broad market"
    return "Thematic"


def _index_frame(client: BhavcopyClient, d: date) -> pd.DataFrame | None:
    """One day's ind_close_all file (name, close, change %, P/E) plus P/B and dividend yield."""
    df = client.index_day(d)
    if df is None or df.empty:
        return None
    df = df.rename(columns={"pct_change": "change_pct"})
    try:
        full = pd.read_csv(io.BytesIO(client._fetch("index", d)), dtype=str)
        cols = {c.strip().lower(): c for c in full.columns}

        def num(key):
            orig = next((o for k, o in cols.items() if key in k), None)
            if orig is None:
                return np.nan
            return pd.to_numeric(full[orig].str.replace(",", "").str.strip(), errors="coerce")
        extra = pd.DataFrame({"name": full[cols["index name"]].str.strip(), "pb": num("p/b"), "dy": num("div")})
        df = df.merge(extra.drop_duplicates("name"), on="name", how="left")
    except Exception as e:  # noqa: BLE001  extras are optional
        log.debug("index extras unavailable for %s: %s", d, e)
    return df


def _sessions_before(client: BhavcopyClient, before: date, need: int = 2, max_back: int = 12):
    """Most recent `need` index files dated strictly before `before` -> [(date, frame)] newest first."""
    out, d = [], before
    for _ in range(max_back):
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        f = _index_frame(client, d)
        if f is not None:
            out.append((d, f))
            if len(out) == need:
                break
    return out


def all_indices(nse: dict, today: date, client: BhavcopyClient | None) -> tuple[list[dict], str]:
    """Every NSE index for the last session. Live NSE snapshot first, official daily index file as fallback."""
    rows = []
    for key, v in nse.items():
        if v.get("last") is None:
            continue
        r = {k: _f(v.get(k)) for k in ("last", "change_pct", "pe", "pb", "dy", "advances", "declines",
                                         "year_high", "year_low", "change_30d", "change_365d")}
        rows.append({"name": v.get("name") or key, "group": index_group(v.get("name") or key, v.get("group", "")), **r})
    source = "NSE (live snapshot)"
    if not rows:
        client = client or BhavcopyClient()
        sess = _sessions_before(client, today, need=2)
        if not sess:
            return [], "unavailable"
        (d, cur), prev = sess[0], (sess[1][1] if len(sess) > 1 else None)
        prev_close = dict(zip(prev["name"], prev["close"])) if prev is not None else {}
        for r in cur.itertuples():
            chg = getattr(r, "change_pct", None)
            if prev_close.get(r.name):  # exact change vs the previous session's file
                chg = (r.close / prev_close[r.name] - 1) * 100
            rows.append({"name": r.name, "group": index_group(r.name), "last": _f(r.close), "change_pct": _f(chg),
                         "pe": _f(getattr(r, "pe", None)), "pb": _f(getattr(r, "pb", None)), "dy": _f(getattr(r, "dy", None))})
        source = f"NSE daily index file ({d.isoformat()})"
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else 99, r["name"]))
    return rows, source


def all_indices_weekly(mon: date, fri: date, client: BhavcopyClient | None) -> list[dict]:
    """Weekly change of every NSE index: last session of the week vs the last session before it."""
    client = client or BhavcopyClient()
    end = _sessions_before(client, fri + timedelta(days=1), need=1, max_back=5)
    start = _sessions_before(client, mon, need=1)
    if not end or not start or end[0][0] < mon:
        return []
    (d_end, e), (_, s0) = end[0], start[0]
    base = dict(zip(s0["name"], s0["close"]))
    rows = []
    for r in e.itertuples():
        if base.get(r.name):
            rows.append({"name": r.name, "group": index_group(r.name), "close": _f(r.close),
                         "change_pct": _f((r.close / base[r.name] - 1) * 100), "pe": _f(getattr(r, "pe", None))})
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else 99, r["name"]))
    return rows


def breadth(today: date, client: BhavcopyClient | None = None) -> dict:
    """Advance/decline and top movers from the last session's NSE bhavcopy (shared cache with the watchlist sync)."""
    client = client or BhavcopyClient()
    for back in range(1, 8):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        try:
            df = client.equity_day(d)
        except Exception as e:  # noqa: BLE001
            return {"breadth": None, "breadth_error": str(e)[:120]}
        if df is None:
            continue
        eq = df[df["series"] == "EQ"].dropna(subset=["prev_close"])
        if eq.empty:
            return {"breadth": None, "breadth_error": "bhavcopy has no previous-close column"}
        eq = eq.assign(chg=(eq["close"] / eq["prev_close"] - 1) * 100)
        liquid = eq[eq["turnover"] >= MIN_TURNOVER] if "turnover" in eq else eq
        cols = ["symbol", "close", "chg", "turnover"]

        def recs(x):
            return [{"symbol": r.symbol, "close": _f(r.close), "change_pct": _f(r.chg),
                     "turnover_cr": _f(r.turnover / 1e7, 1)} for r in x[cols].itertuples()]
        adv, dec = int((eq["chg"] > 0).sum()), int((eq["chg"] < 0).sum())
        if adv + dec == 0:
            return {"breadth": None, "breadth_error": "bhavcopy previous-close values missing"}
        return {"session_date": d.isoformat(),
                "breadth": {"advances": adv, "declines": dec, "unchanged": int(len(eq) - adv - dec),
                            "ratio": _f(adv / dec if dec else None)},
                "gainers": recs(liquid.nlargest(8, "chg")), "losers": recs(liquid.nsmallest(8, "chg"))}
    return {"breadth": None, "breadth_error": "No bhavcopy found for the last 7 days"}


def news_section(http: Http, watch: set[str]) -> dict:
    items = fetch_news(http, NEWS_FEEDS)
    for it in items:
        it["sentiment"] = round(nlp.sentiment(f"{it['title']}. {it['summary'][:200]}"), 3)
    items = nlp.dedupe(items)
    try:
        names = nse_equity_names(http)
        http.note("NSE equity list", True, f"{len(names)} companies")
    except Exception as e:  # noqa: BLE001
        names = {}
        http.note("NSE equity list", False, f"using built-in company list ({str(e)[:60]})")
    linker = nlp.CompanyLinker(CORE_ALIASES, names)
    for it in items:
        it["symbols"] = linker.find(f"{it['title']} {it['summary'][:200]}")
    out = {}
    for region in ("india", "world"):
        sub = [it for it in items if it["region"] == region]
        s = float(np.mean([it["sentiment"] for it in sub])) if sub else 0.0
        th = nlp.themes(sub, max_themes=6)
        in_theme = {id(x) for t in th for x in t["items"]}
        top_idx = nlp.textrank([it["title"] for it in sub], 5) if sub else []
        out[region] = {"count": len(sub), "sentiment": round(s, 3), "label": nlp.label(s),
                       "themes": [{**t, "items": t["items"][:6]} for t in th],
                       "key_stories": [sub[i] for i in top_idx],
                       "other": [it for it in sub if id(it) not in in_theme][:12]}
    stocks = nlp.stocks_in_news(items, linker, limit=20)
    for st in stocks:
        st["watchlist"] = st["symbol"] in watch
    stocks.sort(key=lambda x: (not x["watchlist"], -x["count"]))
    return {"regions": out, "stocks_in_news": stocks, "all_items": items}


def events_section(http: Http, today: date, watch: set[str]) -> dict:
    ev = nse_events(http, today, days=7)
    for e in ev:
        e["watchlist"] = e["symbol"] in watch
    today_s = today.isoformat()
    todays = [e for e in ev if e["date"] == today_s]
    upcoming = [e for e in ev if e["date"] > today_s]
    return {"today": sorted(todays, key=lambda e: (not e["watchlist"], e["symbol"])),
            "upcoming": sorted(upcoming, key=lambda e: (e["date"], not e["watchlist"], e["symbol"]))[:60],
            "results_today": sorted({e["symbol"] for e in todays if "result" in (e["purpose"] + e["detail"]).lower()})}


def flows_section(http: Http, today: date, all_idx: list[dict]) -> dict:
    """FII/DII cash flows, F&O positions of Retail / Pro / FII / DII, and advance/decline."""
    out = {}
    for key, fn in (("fii_dii", lambda: PT.fii_dii(http)),
                    ("participants", lambda: PT.participants_section(http, today)),
                    ("advance_decline", lambda: PT.advance_decline(today, getattr(http, "bhav", None), all_idx))):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001  one failing source never breaks the briefing
            log.exception("%s failed", key)
            out[key] = None if key == "fii_dii" else {"available": False, "reason": str(e)[:160]}
    hist = PT.fii_dii_history([p for p in DAILY_DIR.glob("*.json") if p.stem != today.isoformat()])
    fd = out["fii_dii"]
    if fd and fd.get("date") and all(h["date"] != fd["date"] for h in hist):
        hist.append({"date": fd["date"], "fii": (fd.get("fii") or {}).get("net"), "dii": (fd.get("dii") or {}).get("net")})
    out["fii_dii_history"] = hist[-10:]
    return out


# ------------------------------------------------------------------ narrative

def _pct(v):
    return "n/a" if v is None else f"{v:+.2f}%"


def _cues(glob: list[dict]) -> dict:
    by = {g["symbol"]: g for g in glob if g.get("change_pct") is not None}
    core = [by[s]["change_pct"] for s in ("^GSPC", "^IXIC", "^DJI", "^N225", "^HSI") if s in by]
    score = float(np.mean(core)) if core else 0.0
    lab = ("positive" if score > 0.4 else "mildly positive" if score > 0.1 else
           "negative" if score < -0.4 else "mildly negative" if score < -0.1 else "flat")
    return {"score": round(score, 2), "label": lab}


def narrative(b: dict) -> list[str]:
    g = {x["symbol"]: x for x in b["global"]}
    paras = []
    c = b["mood"]["global_cues"]
    us = ", ".join(f"{g[s]['name']} {_pct(g[s].get('change_pct'))}" for s in ("^GSPC", "^IXIC", "^DJI") if s in g and g[s].get("change_pct") is not None)
    asia = ", ".join(f"{g[s]['name']} {_pct(g[s].get('change_pct'))}" for s in ("^N225", "^HSI", "^KS11") if s in g and g[s].get("change_pct") is not None)
    p = f"Global cues are {c['label']}."
    if us:
        p += f" Overnight in the US: {us}."
    if asia:
        p += f" Asia (latest): {asia}."
    extras = []
    for s, lab in (("BZ=F", "Brent crude"), ("GC=F", "gold"), ("INR=X", "USD/INR"), ("^TNX", "the US 10-year yield")):
        if s in g and g[s].get("last") is not None and g[s].get("change_pct") is not None:
            extras.append(f"{lab} {g[s]['last']:,.2f} ({_pct(g[s]['change_pct'])})")
    if extras:
        txt = "; ".join(extras)
        p += " " + txt[0].upper() + txt[1:] + "."
    paras.append(p)

    ind = {x["name"]: x for x in b["india"]["indices"]}
    n50, bank = ind.get("Nifty 50", {}), ind.get("Nifty Bank", {})
    if n50.get("last"):
        p = f"In the last session ({n50.get('date') or b['india'].get('session_date')}), the Nifty 50 closed at {n50['last']:,.2f} ({_pct(n50.get('change_pct'))})"
        if bank.get("last"):
            p += f" and Nifty Bank at {bank['last']:,.2f} ({_pct(bank.get('change_pct'))})"
        p += "."
        br = b["india"].get("breadth")
        if br:
            tone = "positive" if br["advances"] > br["declines"] * 1.2 else "negative" if br["declines"] > br["advances"] * 1.2 else "mixed"
            p += f" Market breadth was {tone}: {br['advances']:,} advances vs {br['declines']:,} declines."
        sectors = [x for x in b["india"]["indices"] if x["group"] == "Sector" and x.get("change_pct") is not None]
        if sectors:
            best, worst = max(sectors, key=lambda x: x["change_pct"]), min(sectors, key=lambda x: x["change_pct"])
            p += f" {best['name']} led ({_pct(best['change_pct'])}) while {worst['name']} lagged ({_pct(worst['change_pct'])})."
        eq = [x for x in b["india"].get("all_indices", []) if x.get("change_pct") is not None
              and x["group"] != "Fixed income" and "VIX" not in x["name"].upper()]
        if len(eq) >= 10:
            up = sum(x["change_pct"] > 0 for x in eq)
            p += f" Across all {len(eq)} NSE equity indices, {up} rose and {len(eq) - up} fell."
        paras.append(p)

    o = b.get("outlook") or {}
    gap = (o.get("targets") or {}).get("gap_up") if o.get("available") else None
    if gap and gap.get("available"):
        lean = "higher" if gap["prob_up"] >= 0.5 else "lower"
        conf = abs(gap["prob_up"] - 0.5)
        strength = "a slight" if conf < 0.08 else "a moderate" if conf < 0.18 else "a strong"
        shown = min(max(gap["prob_up"], 0.01), 0.99)  # never claim certainty
        p = (f"The pre-market model gives a {shown * 100:.0f}% chance that the Nifty opens above yesterday's close "
             f"— {strength} lean {lean}.")
        p += (" In past testing it beat a naive guess, so it carries some weight." if gap["has_edge"]
              else " It did not reliably beat a naive guess in testing, so treat this as indicative only.")
        paras.append(p)

    nw = b["news"]["regions"]
    parts = []
    for region, lab in (("india", "Indian"), ("world", "global")):
        r = nw.get(region) or {}
        if r.get("count"):
            th = ", ".join(t["label"].replace(" · ", " & ") for t in r["themes"][:3])
            parts.append(f"{lab} news mood is {r['label']} across {r['count']} stories" + (f" (main themes: {th})" if th else ""))
    if parts:
        paras.append("; ".join(parts) + ".")

    ev = b["events"]
    if ev.get("today") or ev.get("results_today"):
        p = f"{len(ev['today'])} corporate events today"
        if ev.get("results_today"):
            shown = ev["results_today"][:8]
            p += f", including results from {', '.join(shown)}" + (" and others" if len(ev["results_today"]) > 8 else "")
        wl = sorted({e["symbol"] for e in ev["today"] if e["watchlist"]})
        if wl:
            p += f". On your watchlist: {', '.join(wl)}"
        paras.append(p + ".")
    wl_news = [s["symbol"] for s in b["news"]["stocks_in_news"] if s["watchlist"]]
    if wl_news:
        paras.append(f"Watchlist stocks in the news: {', '.join(wl_news)}.")
    return paras


# ------------------------------------------------------------------ build / store

def _cleanup_cache(keep_days: int = 10):
    if not CACHE_DIR.exists():
        return
    cutoff = datetime.now(IST).date() - timedelta(days=keep_days)
    for d in CACHE_DIR.iterdir():
        try:
            if date.fromisoformat(d.name) < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except ValueError:
            continue


def build_daily(day: date | None = None, http: Http | None = None, log_fn=None) -> dict:
    now = datetime.now(IST)
    day = day or now.date()
    http = http or Http(day=day)
    say = log_fn or (lambda m: log.info("briefing: %s", m))
    watch = _watchlist()
    b = {"kind": "daily", "date": day.isoformat(), "generated_at": now.isoformat(timespec="seconds")}
    say("World indices, commodities and currencies…")
    b["global"] = global_section(http, day)
    say("Indian indices and market breadth…")
    b["india"] = india_section(http, day)
    say("News feeds (CNBC-TV18, CNBC, Yahoo Finance) and offline NLP…")
    b["news"] = news_section(http, watch)
    say("Stock events (NSE)…")
    b["events"] = events_section(http, day, watch)
    say("FII/DII flows, F&O positions by participant, advance/decline…")
    b["flows"] = flows_section(http, day, b["india"].get("all_indices", []))
    say("Pre-market outlook model…")
    try:
        b["outlook"] = train_and_predict(load_history(http), day)
        http.note("Outlook model", b["outlook"].get("available", False), b["outlook"].get("reason", "trained"))
    except Exception as e:  # noqa: BLE001
        log.exception("outlook failed")
        b["outlook"] = {"available": False, "reason": str(e)[:160]}
    news_all = b["news"]["all_items"]
    ns = float(np.mean([i["sentiment"] for i in news_all])) if news_all else 0.0
    b["mood"] = {"global_cues": _cues(b["global"]),
                 "news": {"score": round(ns, 3), "label": nlp.label(ns), "count": len(news_all)}}
    b["narrative"] = narrative(b)
    fl = b["flows"]
    extra = PT.narrative(fl.get("fii_dii"), fl["participants"], fl["advance_decline"])
    at = next((i + 1 for i, p in enumerate(b["narrative"]) if p.startswith("In the last session")), min(2, len(b["narrative"])))
    b["narrative"][at:at] = extra
    b["sources"] = [{"name": k, **v} for k, v in sorted(http.status.items())]
    b["watchlist"] = sorted(watch)
    (DAILY_DIR / f"{day.isoformat()}.json").write_text(json.dumps(b, default=str))
    _cleanup_cache()
    say("Daily briefing saved.")
    return b


def week_bounds(day: date) -> tuple[date, date]:
    """Monday..Friday of the week to recap: the current week from Friday evening onwards, else the previous one."""
    monday = day - timedelta(days=day.weekday())
    if day.weekday() < 4:  # Mon–Thu: recap last week
        monday -= timedelta(days=7)
    return monday, monday + timedelta(days=4)


def build_weekly(day: date | None = None, http: Http | None = None, log_fn=None) -> dict:
    now = datetime.now(IST)
    day = day or now.date()
    http = http or Http(day=day)
    say = log_fn or (lambda m: log.info("weekly: %s", m))
    mon, fri = week_bounds(day)
    watch = _watchlist()
    say(f"Weekly recap for {mon} to {fri}…")

    def weekly_change(sym):
        df = yahoo_chart(http, sym, "3mo", max_age_h=6).dropna(subset=["close"])
        before = df[df.index < pd.Timestamp(mon)]
        within = df[(df.index >= pd.Timestamp(mon)) & (df.index <= pd.Timestamp(fri))]
        if before.empty or within.empty:
            return None
        start, end = before["close"].iloc[-1], within["close"].iloc[-1]
        return {"close": _f(end, 4), "change_pct": _f((end / start - 1) * 100), "high": _f(within["high"].max(), 4),
                "low": _f(within["low"].min(), 4), "daily": [_f(x, 4) for x in within["close"].tolist()]}

    perf = []
    for sym, name, group, kind in GLOBAL:
        try:
            w = weekly_change(sym)
            if w:
                perf.append({"symbol": sym, "name": name, "group": group, "kind": kind, **w})
        except FetchError:
            continue
    india = []
    for ysym, name, _nse, group in INDIA:
        try:
            w = weekly_change(ysym)
            if w:
                india.append({"symbol": ysym, "name": name, "group": group, **w})
        except FetchError:
            continue
    http.note("Yahoo Finance quotes", bool(perf or india), f"{len(perf) + len(india)} instruments")
    try:
        every = all_indices_weekly(mon, fri, getattr(http, "bhav", None))
    except Exception as e:  # noqa: BLE001
        log.warning("weekly all-index summary failed: %s", e)
        every = []
    http.note("NSE all-index summary", bool(every), f"{len(every)} indices")

    dailies = []
    d = mon
    while d <= fri:
        p = DAILY_DIR / f"{d.isoformat()}.json"
        if p.exists():
            dailies.append(json.loads(p.read_text()))
        d += timedelta(days=1)
    items = [it for b in dailies for it in b["news"]["all_items"]]
    if len(dailies) < 3:  # not enough stored mornings: use what the feeds still carry (~last 7 days)
        say("Few stored daily briefings this week — adding the news feeds' recent history…")
        fresh = fetch_news(http, NEWS_FEEDS, since_hours=24 * 8)
        lo = datetime(mon.year, mon.month, mon.day, tzinfo=IST)
        hi = lo + timedelta(days=7)  # Monday 00:00 .. next Monday 00:00 (weekend news counts towards the week)
        fresh = [it for it in fresh if it["published"] and lo <= datetime.fromisoformat(it["published"]) < hi]
        for it in fresh:
            it["sentiment"] = round(nlp.sentiment(f"{it['title']}. {it['summary'][:200]}"), 3)
        seen = {it["title"] for it in items}
        items += [it for it in fresh if it["title"] not in seen]
    items = nlp.dedupe(items)
    mood_by_day = [{"date": b["date"], "news": b["mood"]["news"]["score"], "global_cues": b["mood"]["global_cues"]["score"],
                    "gap_up_prob": ((b.get("outlook") or {}).get("targets") or {}).get("gap_up", {}).get("prob_up")}
                   for b in dailies]
    # how did the daily pre-market calls do?
    calls = []
    nifty = next((x for x in india if x["symbol"] == "^NSEI"), None)
    try:
        nh = yahoo_chart(http, "^NSEI", "3mo", max_age_h=6)
        for b in dailies:
            g = ((b.get("outlook") or {}).get("targets") or {}).get("gap_up")
            ts = pd.Timestamp(b["date"])
            if not g or not g.get("available") or ts not in nh.index:
                continue
            prev = nh[nh.index < ts]["close"]
            if prev.empty:
                continue
            opened_up = bool(nh.loc[ts, "open"] > prev.iloc[-1])
            calls.append({"date": b["date"], "prob_up": g["prob_up"], "opened_up": opened_up,
                          "correct": (g["prob_up"] >= 0.5) == opened_up})
    except FetchError:
        pass
    # flows over the week: FII/DII per session from stored mornings, participant positions start vs end
    seen, fdays = set(), []
    for b in sorted(dailies, key=lambda x: x["date"]):
        fd = (b.get("flows") or {}).get("fii_dii")
        if fd and fd.get("date") and fd["date"] not in seen and mon.isoformat() <= fd["date"] <= fri.isoformat():
            seen.add(fd["date"])
            fdays.append({"date": fd["date"], "fii": (fd.get("fii") or {}).get("net"), "dii": (fd.get("dii") or {}).get("net")})
    try:
        part_w = PT.participants_weekly(http, mon, fri)
    except Exception as e:  # noqa: BLE001
        part_w = {"available": False, "reason": str(e)[:160]}
    try:
        adw = PT.advance_decline(fri + timedelta(days=1), getattr(http, "bhav", None), [], sessions=5)
        adw["history"] = [h for h in adw["history"] if h["date"] >= mon.isoformat()]
    except Exception as e:  # noqa: BLE001
        adw = {"available": False, "history": [], "reason": str(e)[:160]}
    flows_w = {"fii_dii_days": fdays,
               "fii_net": round(sum(d["fii"] or 0 for d in fdays), 2) if fdays else None,
               "dii_net": round(sum(d["dii"] or 0 for d in fdays), 2) if fdays else None,
               "participants": part_w, "advance_decline": adw}
    linker = nlp.CompanyLinker(CORE_ALIASES, {})
    stocks = nlp.stocks_in_news(items, linker, limit=15)
    for st in stocks:
        st["watchlist"] = st["symbol"] in watch
    ev = nse_events(http, fri + timedelta(days=3), days=5)  # next week
    for e in ev:
        e["watchlist"] = e["symbol"] in watch
    wk = {
        "kind": "weekly", "week_start": mon.isoformat(), "week_end": fri.isoformat(),
        "generated_at": now.isoformat(timespec="seconds"), "global": perf, "india": india, "all_indices": every,
        "mood_by_day": mood_by_day, "premarket_calls": calls,
        "themes": {r: nlp.themes([i for i in items if i["region"] == r], max_themes=6, min_size=2) for r in ("india", "world")},
        "stocks_in_news": sorted(stocks, key=lambda x: (not x["watchlist"], -x["count"])),
        "next_week_events": sorted(ev, key=lambda e: (e["date"], not e["watchlist"], e["symbol"]))[:60],
        "news_count": len(items), "daily_briefings": len(dailies), "flows": flows_w,
    }
    for r in wk["themes"].values():
        for t in r:
            t["items"] = t["items"][:5]
    wk["narrative"] = weekly_narrative(wk, nifty)
    fw = []
    if flows_w["fii_net"] is not None:
        fw.append(f"Over the {len(fdays)} session(s) on record, FIIs were net {'buyers' if flows_w['fii_net'] >= 0 else 'sellers'} of "
                  f"₹{abs(flows_w['fii_net']):,.0f} cr and DIIs net {'buyers' if (flows_w['dii_net'] or 0) >= 0 else 'sellers'} of "
                  f"₹{abs(flows_w['dii_net'] or 0):,.0f} cr in the cash market.")
    if part_w.get("available"):
        f = next((r for r in part_w["rows"] if r["code"] == "FII"), None)
        if f and f.get("change"):
            fw.append(f"FIIs ended the week {f['index_fut']['long_pct']:.0f}% long in index futures, "
                      f"a net change of {f['change']['index_fut_net']:+,.0f} contracts over the week.")
    if adw.get("history"):
        a, d = sum(h["advances"] for h in adw["history"]), sum(h["declines"] for h in adw["history"])
        fw.append(f"Breadth over the week: {a:,} advances vs {d:,} declines across {len(adw['history'])} sessions.")
    wk["narrative"][1:1] = fw
    wk["sources"] = [{"name": k, **v} for k, v in sorted(http.status.items())]
    (WEEKLY_DIR / f"{mon.isoformat()}.json").write_text(json.dumps(wk, default=str))
    say("Weekly recap saved.")
    return wk


def weekly_narrative(wk: dict, nifty: dict | None) -> list[str]:
    paras = []
    if nifty:
        p = f"The Nifty 50 ended the week at {nifty['close']:,.2f}, {_pct(nifty['change_pct'])} for the week."
        sectors = [x for x in wk["india"] if x["group"] == "Sector" and x.get("change_pct") is not None]
        if sectors:
            s = sorted(sectors, key=lambda x: x["change_pct"])
            p += f" Best sector: {s[-1]['name']} ({_pct(s[-1]['change_pct'])}); weakest: {s[0]['name']} ({_pct(s[0]['change_pct'])})."
        paras.append(p)
    idx = [x for x in wk["global"] if x["kind"] == "index" and x["symbol"] != "^VIX" and x.get("change_pct") is not None]
    if idx:
        s = sorted(idx, key=lambda x: x["change_pct"])
        paras.append(f"Globally, {s[-1]['name']} led ({_pct(s[-1]['change_pct'])}) and {s[0]['name']} lagged "
                     f"({_pct(s[0]['change_pct'])}). "
                     + ", ".join(f"{x['name']} {_pct(x['change_pct'])}" for x in wk["global"] if x["symbol"] in ("^GSPC", "^IXIC", "^N225", "^HSI")) + ".")
    eq = [x for x in wk.get("all_indices", []) if x.get("change_pct") is not None
          and x["group"] != "Fixed income" and "VIX" not in x["name"].upper()]
    if len(eq) >= 10:
        s = sorted(eq, key=lambda x: x["change_pct"])
        up = sum(x["change_pct"] > 0 for x in eq)
        paras.append(f"{up} of {len(eq)} NSE equity indices gained over the week. Best: {s[-1]['name']} ({_pct(s[-1]['change_pct'])}); "
                     f"worst: {s[0]['name']} ({_pct(s[0]['change_pct'])}).")
    th = [t["label"].replace(" · ", " & ") for r in ("india", "world") for t in wk["themes"][r][:2]]
    if th:
        paras.append(f"Recurring news themes this week: {', '.join(th)}.")
    if wk["premarket_calls"]:
        right = sum(c["correct"] for c in wk["premarket_calls"])
        paras.append(f"The pre-market model called the opening direction correctly on {right} of {len(wk['premarket_calls'])} days this week.")
    if wk["next_week_events"]:
        res = sorted({e["symbol"] for e in wk["next_week_events"] if "result" in (e["purpose"] + e["detail"]).lower()})
        if res:
            paras.append(f"Results due next week include {', '.join(res[:10])}" + (" and more." if len(res) > 10 else "."))
    return paras


def load(kind: str, key: str | None = None) -> dict | None:
    folder = DAILY_DIR if kind == "daily" else WEEKLY_DIR
    if key:
        p = folder / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None
    files = sorted(folder.glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


def list_saved(kind: str) -> list[str]:
    folder = DAILY_DIR if kind == "daily" else WEEKLY_DIR
    return sorted((p.stem for p in folder.glob("*.json")), reverse=True)
