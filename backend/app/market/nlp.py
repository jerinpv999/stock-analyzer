"""Offline news NLP — no cloud AI, no model downloads by default.

  * sentiment()      finance-tuned lexicon with negation and phrase rules (or FinBERT if you opt in)
  * dedupe()         merges the same story reported by several feeds (TF-IDF cosine similarity)
  * themes()         clusters stories into topics and labels them by their key terms
  * textrank()       extractive summary: picks the most central sentences
  * CompanyLinker    finds NSE-listed companies mentioned in headlines
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ sentiment

POS = set("""
gain gains gained gaining rally rallies rallied rallying surge surges surged surging jump jumps jumped jumping
soar soars soared soaring climb climbs climbed climbing rise rises rising rose advance advances advanced rebound
rebounds rebounded recover recovers recovered recovery up upbeat bullish optimism optimistic strong stronger strength
robust record beat beats beating outperform outperforms outperformed upgrade upgrades upgraded boost boosts boosted
growth grow grows grew expand expands expanded expansion profit profits profitable positive buy buying inflow inflows
higher high highs peak breakout momentum resilient easing eases eased cooling stimulus approval approves approved
win wins won deal deals rate-cut cuts dividend bonus buyback upside accelerate accelerates beat-estimates
""".split())
NEG = set("""
fall falls fell falling drop drops dropped dropping decline declines declined declining slump slumps slumped
plunge plunges plunged plunging tumble tumbles tumbled tumbling slide slides slid sink sinks sank crash crashes crashed
loss losses lose loses losing lost weak weaker weakness bearish pessimism fear fears worried worry worries concern
concerns risk risks volatile volatility selloff sell-off selling outflow outflows lower low lows miss misses missed
downgrade downgrades downgraded cut slowdown slows slowed slowing recession inflation default defaults debt crisis
war conflict tariff tariffs sanctions probe penalty fine fined fraud scam lawsuit ban banned layoffs layoff
shutdown strike strikes warning warns warned negative uncertainty uncertain pressure pressured drag drags dragged
underperform underperforms underperformed downside slip slips slipped hit hits tension tensions dispute halt halted
""".split())
PHRASES = {  # checked before single words; value replaces the words' own scores
    "record high": 2, "all-time high": 2, "beat estimates": 2, "beats estimates": 2, "rate cut": 1, "rate cuts": 1,
    "profit booking": -1, "profit-taking": -1, "rate hike": -1, "rate hikes": -1, "misses estimates": -3,
    "missed estimates": -3, "52-week low": -2, "52-week high": 2, "lower circuit": -2, "upper circuit": 2,
    "fii selling": -1, "fii buying": 1, "fpi outflows": -1, "fpi inflows": 1, "gap-up": 1, "gap-down": -1,
    "cut to": 0, "price target cut": -1, "target raised": 1, "raises target": 1, "cuts target": -1,
}
NEGATORS = {"not", "no", "never", "without", "despite", "fails", "failed", "unlikely", "barely"}
INTENS = {"sharply": 1.5, "steeply": 1.5, "massive": 1.5, "biggest": 1.4, "huge": 1.4, "slightly": 0.6,
          "marginally": 0.5, "modestly": 0.7, "mildly": 0.6}
_WORD = re.compile(r"[a-z][a-z0-9'&\-]*")

_finbert = None


def _finbert_pipe():
    global _finbert
    if _finbert is None:
        from transformers import pipeline  # optional dependency
        _finbert = pipeline("text-classification", model="ProsusAI/finbert", truncation=True)
    return _finbert


def sentiment(text: str) -> float:
    """-1 (very negative) .. +1 (very positive)."""
    if os.getenv("SENTIMENT_BACKEND", "").lower() == "finbert":
        try:
            r = _finbert_pipe()(text[:512])[0]
            return {"positive": 1, "negative": -1}.get(r["label"].lower(), 0) * float(r["score"])
        except Exception as e:  # noqa: BLE001
            log.warning("FinBERT unavailable (%s) — using lexicon", e)
            os.environ["SENTIMENT_BACKEND"] = "lexicon"
    t = text.lower()
    score, hits = 0.0, 0
    for ph, v in PHRASES.items():
        if ph in t:
            score += v
            hits += 1
            t = t.replace(ph, " ")
    words = _WORD.findall(t)
    for i, w in enumerate(words):
        v = 1 if w in POS else -1 if w in NEG else 0
        if not v:
            continue
        window = words[max(0, i - 3):i]
        if any(x in NEGATORS for x in window):
            v = -v
        for x in window:
            v *= INTENS.get(x, 1)
        score += v
        hits += 1
    if not hits:
        return 0.0
    return float(np.tanh(score / 2.5))


def label(score: float) -> str:
    return "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"


# ------------------------------------------------------------------ text similarity

NEWS_STOP = set(ENGLISH_STOP_WORDS) | {
    "says", "said", "say", "new", "news", "today", "live", "updates", "update", "stock", "stocks", "market",
    "markets", "share", "shares", "check", "know", "here", "what", "why", "how", "amid", "after", "ahead",
    "week", "day", "year", "time", "percent", "cent", "rs", "crore", "cr", "lakh", "inr", "usd", "trade",
    "trading", "investors", "report", "reports", "according", "latest", "top", "key", "could", "may", "will",
}


# Direction words say how a market moved, not what a story is about. They drive sentiment,
# but are kept out of topic clustering so "Nifty rises" and "inflation rises" don't merge.
MOVE_WORDS = {
    "gain", "gains", "gained", "rally", "rallies", "rallied", "surge", "surges", "surged", "jump", "jumps", "jumped",
    "soar", "soars", "soared", "climb", "climbs", "climbed", "rise", "rises", "rising", "rose", "advance", "advances",
    "rebound", "rebounds", "recover", "recovers", "up", "higher", "high", "highs", "fall", "falls", "fell", "falling",
    "drop", "drops", "dropped", "decline", "declines", "declined", "slump", "slumps", "plunge", "plunges", "tumble",
    "tumbles", "tumbled", "slide", "slides", "slid", "sink", "sinks", "sank", "slip", "slips", "slipped", "lower", "low",
    "lows", "ease", "eases", "eased", "edge", "edges", "edged", "steady", "steadies", "mixed", "flat", "end", "ends",
    "ended", "close", "closes", "closed", "open", "opens", "opened", "extend", "extends", "snap", "snaps", "streak",
    "pressure", "weigh", "weighs", "drag", "drags", "dragged", "lead", "leads", "led", "boost", "boosts", "rise",
    "strong", "weak", "stronger", "weaker", "early", "session", "points", "pct", "%", "nearly", "most", "mostly",
    "continue", "continues", "straight", "fourth", "third", "second", "first", "big", "biggest", "sharp", "sharply",
}
_TOK = re.compile(r"[a-z][a-z0-9&\-]{1,}")


def _stem(w: str) -> str:
    """Tiny suffix stripper so 'ends/ended/ending' and 'drags/dragged' match."""
    for suf, keep in (("ing", 4), ("ied", 3), ("ies", 3), ("ed", 4), ("es", 4), ("s", 3)):
        if w.endswith(suf) and len(w) - len(suf) >= keep and not (suf == "s" and w.endswith("ss")):
            w = w[: -len(suf)]
            if suf in ("ied", "ies"):
                w += "y"
            elif len(w) > 3 and w[-1] == w[-2] and w[-1] not in "ls":  # dragg -> drag
                w = w[:-1]
            break
    return w


def _unigrams(doc: str) -> list[str]:
    return [_stem(t) for t in _TOK.findall(doc.lower()) if t not in NEWS_STOP and t not in MOVE_WORDS]


def _analyze(doc: str) -> list[str]:
    toks = _unigrams(doc)
    return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]


def _vec(min_df=1, bigrams=True):
    return TfidfVectorizer(analyzer=_analyze if bigrams else _unigrams, min_df=min_df, sublinear_tf=True)


def _text(it: dict) -> str:
    # linked company symbols act as strong shared tokens, so stories about the same company cluster
    tags = " ".join(f"zz{re.sub(r'[^a-z0-9]', '', s.lower())}" for s in it.get("symbols") or [])
    return f"{it['title']}. {it['title']}. {it.get('summary', '')} {tags} {tags} {tags}"


def dedupe(items: list[dict], threshold: float = 0.5) -> list[dict]:
    """Collapse near-identical stories; keep the first (newest) and count the duplicates."""
    if len(items) < 2:
        return items
    try:
        X = _vec(bigrams=False).fit_transform([it["title"] for it in items])
    except ValueError:
        return items
    sim = cosine_similarity(X)
    keep, merged = [], set()
    for i, it in enumerate(items):
        if i in merged:
            continue
        dups = [j for j in range(i + 1, len(items)) if j not in merged and sim[i, j] >= threshold]
        merged.update(dups)
        it = dict(it)
        it["also_in"] = sorted({items[j]["source"] for j in dups} - {it["source"]})
        keep.append(it)
    return keep


def textrank(sentences: list[str], k: int = 3) -> list[int]:
    """Indices of the k most central sentences (PageRank over TF-IDF similarity)."""
    n = len(sentences)
    if n <= k:
        return list(range(n))
    try:
        X = _vec().fit_transform(sentences)
    except ValueError:
        return list(range(k))
    S = cosine_similarity(X)
    np.fill_diagonal(S, 0)
    rows = S.sum(axis=1, keepdims=True)
    P = np.divide(S, rows, out=np.full_like(S, 1 / n), where=rows > 0)
    r = np.full(n, 1 / n)
    for _ in range(60):
        r = 0.15 / n + 0.85 * P.T @ r
    return list(np.argsort(-r)[:k])


def themes(items: list[dict], max_themes: int = 6, min_size: int = 2) -> list[dict]:
    """Cluster stories into topics. Returns [{label, keywords, items, sentiment, summary}] biggest first."""
    if len(items) < 3:
        return []
    docs = [_text(it) for it in items]
    try:
        vec = _vec(bigrams=False)  # unigrams cluster better; bigrams are used for labels below
        X = vec.fit_transform(docs)
    except ValueError:
        return []
    terms = np.array(vec.get_feature_names_out())
    surface = defaultdict(Counter)  # stem -> original spellings (case kept: "HDFC", "Fed", "oil")
    for it in items:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9&\-]{1,}", it["title"]):
            if w.lower() not in NEWS_STOP and w.lower() not in MOVE_WORDS:
                surface[_stem(w.lower())][w] += 1

    def readable(term: str) -> str:
        return " ".join(surface[t].most_common(1)[0][0] if surface.get(t) else t for t in term.split())
    cl = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average", distance_threshold=0.8)
    labels = cl.fit_predict(X.toarray())
    groups = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[lab].append(i)
    out = []
    for idx in groups.values():
        if len(idx) < min_size:
            continue
        centroid = np.asarray(X[idx].mean(axis=0)).ravel()
        weight = {terms[j]: centroid[j] for j in np.argsort(-centroid)[:40]}
        df_ = Counter()
        for i in idx:
            df_.update(set(_analyze(items[i]["title"])))
        shared = [t for t, c in df_.items() if c >= 2 and not t.startswith("zz")]
        shared.sort(key=lambda t: (-df_[t], -(" " in t), -weight.get(t, 0)))
        top = shared[:8] or [t for t in weight if not t.startswith("zz")][:8]
        kw = []
        for t in top:  # avoid labels like "China Demand · China"
            tw = set(t.split())
            if any(tw <= set(k.split()) for k in kw):
                continue
            kw = [k for k in kw if not set(k.split()) <= tw]
            kw.append(t)
        kw = kw[:3]
        members = [items[i] for i in idx]
        sents = [it["title"] for it in members]
        best = textrank(sents, 1)[0]
        s = float(np.mean([it["sentiment"] for it in members]))
        kw = [readable(k) for k in kw]
        out.append({"label": " · ".join(k[:1].upper() + k[1:] for k in kw), "keywords": kw, "size": len(members),
                    "sentiment": s, "summary": sents[best],
                    "items": sorted(members, key=lambda x: x.get("published") or "", reverse=True)})
    out.sort(key=lambda g: -g["size"])
    return out[:max_themes]


# ------------------------------------------------------------------ company linking

COMMON = {"india", "indian", "bank", "power", "capital", "finance", "financial", "global", "international",
          "energy", "industries", "industry", "united", "national", "general", "first", "best", "star", "sun",
          "future", "tata", "adani", "bajaj", "birla", "jindal", "mahindra", "reliance", "hdfc", "icici", "state",
          "new", "life", "insurance", "motors", "steel", "cement", "infra", "india's", "gold", "silver", "oil",
          "gas", "the", "and", "of", "technologies", "systems", "services", "solutions", "products", "chemicals",
          "pharma", "pharmaceuticals", "electric", "electricals", "foods", "sugar", "textiles", "housing"}


def _clean_name(name: str) -> str:
    n = re.sub(r"\b(limited|ltd\.?|the|co\.?|corporation|company)\b", " ", name, flags=re.I)
    n = re.sub(r"[().,]", " ", n)
    return re.sub(r"\s+", " ", n).strip().lower()


class CompanyLinker:
    def __init__(self, core_aliases: dict[str, str], equity_names: dict[str, str] | None = None):
        self.multi: dict[str, str] = {}
        self.single: dict[str, str] = {}
        for sym, name in (equity_names or {}).items():
            cn = _clean_name(name)
            words = cn.split()
            if len(words) >= 2 and not all(w in COMMON for w in words):
                self.multi.setdefault(cn, sym)
                if len(words) >= 3 and words[0] not in COMMON and words[1] not in COMMON:
                    self.multi.setdefault(" ".join(words[:2]), sym)
            elif len(words) == 1 and len(words[0]) >= 6 and words[0] not in COMMON:
                self.single.setdefault(words[0], sym)
        listed = set(equity_names or {})
        for alias, sym in core_aliases.items():  # curated aliases win…
            if listed and sym not in listed:  # …unless NSE no longer lists that symbol (renamed / demerged)
                continue
            key = " ".join(self._toks(alias)[1])
            (self.multi if " " in key else self.single)[key] = sym
        self.multi = {" ".join(self._toks(k)[1]): v for k, v in self.multi.items()}
        self.max_n = max((len(a.split()) for a in self.multi), default=1)

    @staticmethod
    def _toks(text: str):
        toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'\u2019\-]*", text.replace("\u2019", "'"))
        return toks, [t.lower().strip("'") for t in toks]

    def find(self, text: str) -> list[str]:
        toks, low = self._toks(text)
        found = []
        i = 0
        while i < len(toks):
            hit = None
            for n in range(min(self.max_n, len(toks) - i), 1, -1):
                key = " ".join(low[i:i + n])
                if key in self.multi:
                    hit = (self.multi[key], n)
                    break
            if not hit:
                w = low[i]
                if w.endswith("'s"):
                    w = w[:-2]
                orig = toks[i]
                if w in self.single and (orig[0].isupper()):  # proper noun / ticker-style only
                    hit = (self.single[w], 1)
            if hit:
                if hit[0] not in found:
                    found.append(hit[0])
                i += hit[1]
            else:
                i += 1
        return found


def stocks_in_news(items: list[dict], linker: CompanyLinker, limit: int = 15) -> list[dict]:
    agg: dict[str, dict] = {}
    for it in items:
        for sym in linker.find(f"{it['title']} {it.get('summary', '')[:200]}"):
            a = agg.setdefault(sym, {"symbol": sym, "count": 0, "sentiment_sum": 0.0, "headlines": []})
            a["count"] += 1
            a["sentiment_sum"] += it["sentiment"]
            if len(a["headlines"]) < 3:
                a["headlines"].append({"title": it["title"], "link": it["link"], "source": it["source"]})
    out = []
    for a in agg.values():
        a["sentiment"] = a.pop("sentiment_sum") / a["count"]
        out.append(a)
    out.sort(key=lambda x: (-x["count"], -abs(x["sentiment"])))
    return out[:limit]


def keyword_counts(items: list[dict], top: int = 12) -> list[tuple[str, int]]:
    c = Counter()
    for it in items:
        words = {w for w in re.findall(r"[a-z][a-z\-]{3,}", it["title"].lower()) if w not in NEWS_STOP}
        c.update(words)
    return c.most_common(top)
