"""Who is buying and selling: FII/DII cash flows, F&O positions by participant, advance/decline.

Sources (NSE, published after each session — so at 08:15 IST they describe the previous session)
  * FII/DII cash-market activity (provisional): https://www.nseindia.com/api/fiidiiTradeReact
  * Participant-wise open interest in equity derivatives (public archive, one CSV per day):
      https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv
    rows: Client (retail and other individual/corporate clients), DII, FII, Pro (brokers' own trading), TOTAL
  * Advance/decline: computed from the NSE equity bhavcopy (all EQ-series stocks), per index from NSE's snapshot.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from ..bhavcopy import BhavcopyClient
from .sources import FetchError, Http, _nse_json

log = logging.getLogger(__name__)

OI_URLS = ("https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{dmy}.csv",
           "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{dmy}.csv")
PARTICIPANTS = [("CLIENT", "Retail (Client)"), ("PRO", "Pro traders"), ("FII", "FII / FPI"), ("DII", "DII")]
COLS = {  # normalised NSE header -> short key
    "future index long": "fi_long", "future index short": "fi_short",
    "future stock long": "fs_long", "future stock short": "fs_short",
    "option index call long": "oic_long", "option index put long": "oip_long",
    "option index call short": "oic_short", "option index put short": "oip_short",
    "option stock call long": "osc_long", "option stock put long": "osp_long",
    "option stock call short": "osc_short", "option stock put short": "osp_short",
    "total long contracts": "total_long", "total short contracts": "total_short",
}


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _r(v, d=1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)


# ------------------------------------------------------------------ FII / DII cash market

def fii_dii(http: Http) -> dict | None:
    """{'date', 'fii': {buy, sell, net}, 'dii': {...}} in ₹ crore, or None if NSE didn't answer."""
    try:
        data = _nse_json(http, "https://www.nseindia.com/api/fiidiiTradeReact")
    except Exception as e:  # noqa: BLE001
        http.note("NSE FII/DII", False, str(e)[:120])
        return None
    rows = data if isinstance(data, list) else data.get("data", [])
    out = {"date": None}
    for r in rows:
        low = {k.lower(): v for k, v in r.items()}
        cat = str(low.get("category", "")).upper()
        who = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
        if not who:
            continue
        buy = _num(next((v for k, v in low.items() if "buy" in k), None))
        sell = _num(next((v for k, v in low.items() if "sell" in k), None))
        net = _num(next((v for k, v in low.items() if "net" in k), None))
        if net is None and buy is not None and sell is not None:
            net = buy - sell
        out[who] = {"buy": _r(buy, 2), "sell": _r(sell, 2), "net": _r(net, 2)}
        d = low.get("date")
        if d and not out["date"]:
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    out["date"] = datetime.strptime(str(d).strip(), fmt).date().isoformat()
                    break
                except ValueError:
                    continue
    if "fii" not in out and "dii" not in out:
        http.note("NSE FII/DII", False, "unexpected response format")
        return None
    http.note("NSE FII/DII", True, f"session {out['date'] or 'unknown'}")
    return out


# ------------------------------------------------------------------ participant-wise OI

def parse_participant_oi(raw: bytes) -> tuple[date | None, dict[str, dict[str, float]]]:
    text = raw.decode("utf-8-sig", errors="replace")
    head = text[:300].lower()
    if "<html" in head or "<!doctype" in head:
        raise FetchError("got a web page instead of the CSV")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hi = next(i for i, ln in enumerate(lines) if "client type" in ln.lower())
    as_of = None
    m = re.search(r"as on\s+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", " ".join(lines[:hi]), re.I)
    if m:
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
            try:
                as_of = datetime.strptime(m.group(1).replace(".", ""), fmt).date()
                break
            except ValueError:
                continue
    df = pd.read_csv(io.StringIO("\n".join(lines[hi:])), dtype=str)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in df.columns]
    out = {}
    for _, r in df.iterrows():
        who = re.sub(r"\s+", "", str(r.get("client type", ""))).upper()
        if who in ("CLIENT", "PRO", "FII", "DII", "TOTAL"):
            out[who] = {key: _num(r[col]) for col, key in COLS.items() if col in df.columns}
    if not {"CLIENT", "FII"} <= set(out):
        raise FetchError("participant rows missing")
    return as_of, out


def _oi_day(http: Http, d: date):
    last = None
    for tmpl in OI_URLS:
        try:
            raw = http.get(tmpl.format(dmy=d.strftime("%d%m%Y")), max_age_h=24 * 30)
            as_of, rows = parse_participant_oi(raw)
            if as_of and as_of != d:  # NSE sometimes serves a previous file under a new name
                return None
            return rows
        except FetchError as e:
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
    log.debug("participant OI %s unavailable: %s", d, last)
    return None


def _sessions(http: Http, before: date, n: int, max_back: int = 21):
    out, d = [], before
    for _ in range(max_back):
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        rows = _oi_day(http, d)
        if rows:
            out.append((d, rows))
            if len(out) == n:
                break
    return out  # newest first


def _summarise(rows: dict, prev: dict | None) -> list[dict]:
    res = []
    for code, label in PARTICIPANTS:
        r = rows.get(code)
        if not r:
            continue

        def g(k):
            return r.get(k) or 0.0
        fi_net = g("fi_long") - g("fi_short")
        fi_tot = g("fi_long") + g("fi_short")
        fs_net = g("fs_long") - g("fs_short")
        call_net = g("oic_long") - g("oic_short")
        put_net = g("oip_long") - g("oip_short")
        row = {
            "code": code, "label": label,
            "index_fut": {"long": g("fi_long"), "short": g("fi_short"), "net": fi_net,
                          "long_pct": _r(g("fi_long") / fi_tot * 100) if fi_tot else None},
            "stock_fut": {"long": g("fs_long"), "short": g("fs_short"), "net": fs_net},
            "index_calls": {"long": g("oic_long"), "short": g("oic_short"), "net": call_net},
            "index_puts": {"long": g("oip_long"), "short": g("oip_short"), "net": put_net},
            # long calls & short puts gain if the index rises; long puts & short calls gain if it falls
            "index_opt_bias": call_net - put_net,
            "total": {"long": g("total_long"), "short": g("total_short")},
        }
        p = (prev or {}).get(code)
        if p:
            row["change"] = {
                "index_fut_net": fi_net - ((p.get("fi_long") or 0) - (p.get("fi_short") or 0)),
                "index_calls_net": call_net - ((p.get("oic_long") or 0) - (p.get("oic_short") or 0)),
                "index_puts_net": put_net - ((p.get("oip_long") or 0) - (p.get("oip_short") or 0)),
                "stock_fut_net": fs_net - ((p.get("fs_long") or 0) - (p.get("fs_short") or 0)),
            }
        res.append(row)
    return res


def participants_section(http: Http, today: date, history: int = 10) -> dict:
    sess = _sessions(http, today, history + 1)
    if not sess:
        http.note("NSE participant-wise OI", False, "no file found for the last 3 weeks")
        return {"available": False, "reason": "NSE participant-wise open interest file not available."}
    (d, rows), prev = sess[0], (sess[1][1] if len(sess) > 1 else None)
    http.note("NSE participant-wise OI", True, f"session {d.isoformat()}")
    trend = []
    for dd, rr in reversed(sess[:history]):
        pt = {"date": dd.isoformat()}
        for code, _ in PARTICIPANTS:
            x = rr.get(code)
            if not x:
                continue
            lo, sh = x.get("fi_long") or 0, x.get("fi_short") or 0
            pt[f"{code.lower()}_fut_net"] = lo - sh
            pt[f"{code.lower()}_fut_long_pct"] = _r(lo / (lo + sh) * 100) if lo + sh else None
        trend.append(pt)
    return {"available": True, "session_date": d.isoformat(), "prev_date": sess[1][0].isoformat() if prev else None,
            "rows": _summarise(rows, prev), "trend": trend}


def participants_weekly(http: Http, mon: date, fri: date) -> dict:
    """Positions at the end of the week vs the end of the previous week."""
    end = _sessions(http, fri + timedelta(days=1), 1, max_back=5)
    start = _sessions(http, mon, 1)
    if not end or end[0][0] < mon or not start:
        return {"available": False, "reason": "participant-wise OI files for that week are not available."}
    return {"available": True, "session_date": end[0][0].isoformat(), "prev_date": start[0][0].isoformat(),
            "rows": _summarise(end[0][1], start[0][1])}


# ------------------------------------------------------------------ advance / decline

def _ad_day(df: pd.DataFrame) -> dict | None:
    eq = df[df["series"] == "EQ"].dropna(subset=["prev_close", "close"])
    if eq.empty:
        return None
    chg = eq["close"] / eq["prev_close"] - 1
    adv, dec = int((chg > 0).sum()), int((chg < 0).sum())
    if adv + dec == 0:
        return None
    return {"advances": adv, "declines": dec, "unchanged": int(len(eq) - adv - dec),
            "ratio": _r(adv / dec, 2) if dec else None,
            "up_4pct": int((chg >= 0.04).sum()), "down_4pct": int((chg <= -0.04).sum())}


def advance_decline(today: date, client: BhavcopyClient | None, all_indices: list[dict], sessions: int = 10) -> dict:
    client = client or BhavcopyClient()
    hist, d = [], today
    for _ in range(sessions * 2 + 6):
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        try:
            df = client.equity_day(d)
        except Exception as e:  # noqa: BLE001
            log.warning("advance/decline %s: %s", d, e)
            break
        if df is None:
            continue
        x = _ad_day(df)
        if x:
            hist.append({"date": d.isoformat(), **x})
        if len(hist) == sessions:
            break
    hist.reverse()
    by_index = [{"name": r["name"], "group": r["group"], "advances": r["advances"], "declines": r["declines"],
                 "change_pct": r.get("change_pct")}
                for r in all_indices if r.get("advances") is not None and r.get("declines") is not None
                and (r["advances"] + r["declines"]) > 0
                and "VIX" not in r["name"].upper() and r.get("group") != "Fixed income"]  # no constituent stocks
    order = ["NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 500", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "NIFTY BANK"]
    by_index.sort(key=lambda r: (order.index(r["name"].upper()) if r["name"].upper() in order else 99, r["group"], r["name"]))
    latest = hist[-1] if hist else None
    return {"available": bool(hist), "latest": latest, "history": hist, "by_index": by_index}


# ------------------------------------------------------------------ text

def _cr(v):
    return "n/a" if v is None else f"₹{abs(v):,.0f} cr"


def narrative(fd: dict | None, part: dict, ad: dict) -> list[str]:
    paras = []
    if fd and (fd.get("fii") or fd.get("dii")):
        bits = []
        for who, lab in (("fii", "FIIs"), ("dii", "DIIs")):
            x = fd.get(who)
            if x and x.get("net") is not None:
                bits.append(f"{lab} were net {'buyers' if x['net'] >= 0 else 'sellers'} of {_cr(x['net'])}")
        if bits:
            paras.append(f"Cash market ({fd.get('date') or 'last session'}, provisional): " + " and ".join(bits) + ".")
    if part.get("available"):
        rows = {r["code"]: r for r in part["rows"]}
        f, c = rows.get("FII"), rows.get("CLIENT")
        if f and f["index_fut"]["long_pct"] is not None:
            p = (f"In index futures, FIIs are {f['index_fut']['long_pct']:.0f}% long "
                 f"(net {f['index_fut']['net']:+,.0f} contracts")
            ch = (f.get("change") or {}).get("index_fut_net")
            if ch is not None:
                p += f", {ch:+,.0f} vs the previous session"
            p += ")"
            if c and c["index_fut"]["long_pct"] is not None:
                p += f", while retail clients are {c['index_fut']['long_pct']:.0f}% long"
            paras.append(p + ".")
    if ad.get("available") and ad.get("latest"):
        x = ad["latest"]
        tone = "positive" if x["advances"] > x["declines"] * 1.2 else "negative" if x["declines"] > x["advances"] * 1.2 else "mixed"
        p = f"Advance/decline was {tone}: {x['advances']:,} stocks rose and {x['declines']:,} fell"
        if x.get("ratio"):
            p += f" (ratio {x['ratio']:.2f})"
        h = ad["history"]
        if len(h) >= 5:
            pos = sum(1 for y in h if y["advances"] > y["declines"])
            p += f"; advances beat declines on {pos} of the last {len(h)} sessions"
        paras.append(p + ".")
    return paras


def fii_dii_history(daily_files, limit: int = 10) -> list[dict]:
    """FII/DII nets from stored morning briefings (one per session, oldest first)."""
    seen, out = set(), []
    for p in sorted(daily_files, reverse=True):
        try:
            b = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        fd = (b.get("flows") or {}).get("fii_dii")
        if not fd or not fd.get("date") or fd["date"] in seen:
            continue
        seen.add(fd["date"])
        out.append({"date": fd["date"], "fii": (fd.get("fii") or {}).get("net"), "dii": (fd.get("dii") or {}).get("net")})
        if len(out) == limit:
            break
    return list(reversed(out))
