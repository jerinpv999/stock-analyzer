"""ChromaDB memory: every analysis summary is embedded and stored so the next
analysis of the same stock can recall what was said before, check whether
earlier calls played out, and surface similar past setups."""
from __future__ import annotations

import logging
from datetime import datetime

import chromadb
import pandas as pd

from .config import CHROMA_DIR, EMBEDDING_BACKEND

log = logging.getLogger(__name__)


def _make_embedder():
    want = EMBEDDING_BACKEND
    if want in ("", "sentence_transformers"):
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            m = SentenceTransformer("all-MiniLM-L6-v2")
            return (lambda t: m.encode(list(t), normalize_embeddings=True).tolist()), "st_minilm"
        except Exception as e:  # noqa: BLE001
            log.info("sentence-transformers unavailable (%s)", e)
    if want in ("", "onnx"):
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            ef = DefaultEmbeddingFunction()
            ef(["warm up"])  # downloads the ONNX MiniLM model on first use
            return (lambda t: [[float(x) for x in v] for v in ef(list(t))]), "onnx_minilm"
        except Exception as e:  # noqa: BLE001
            log.warning("ChromaDB ONNX embedder unavailable (%s) — falling back to hashing embedder", e)
    from sklearn.feature_extraction.text import HashingVectorizer

    hv = HashingVectorizer(n_features=768, ngram_range=(1, 2), norm="l2", alternate_sign=False)
    return (lambda t: hv.transform(list(t)).toarray().tolist()), "hashing"


def _clean_meta(meta: dict) -> dict:
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (bool, int, float, str)):
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except Exception:  # noqa: BLE001
                out[k] = str(v)
    return out


class AnalysisMemory:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.embed, self.backend = _make_embedder()
        # one collection per embedding backend so vector dimensions never clash
        self.col = self.client.get_or_create_collection(
            name=f"stock_analysis_{self.backend}", metadata={"hnsw:space": "cosine"}, embedding_function=None,
        )
        log.info("ChromaDB ready (%s), %d stored analyses", self.backend, self.col.count())

    # ------------------------------------------------------------ write
    def store(self, summary: str, meta: dict) -> str:
        doc_id = f"{meta['symbol']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.col.add(ids=[doc_id], documents=[summary], embeddings=self.embed([summary]),
                     metadatas=[_clean_meta(meta)])
        return doc_id

    # ------------------------------------------------------------- read
    def history(self, symbol: str, limit: int = 50) -> list[dict]:
        res = self.col.get(where={"symbol": symbol}, include=["documents", "metadatas"])
        items = [{"id": i, "summary": d, **m} for i, d, m in zip(res["ids"], res["documents"], res["metadatas"])]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]

    def similar(self, text: str, symbol: str | None = None, k: int = 4, exclude_symbol: bool = False) -> list[dict]:
        if self.col.count() == 0:
            return []
        where = None
        if symbol:
            where = {"symbol": {"$ne": symbol}} if exclude_symbol else {"symbol": symbol}
        try:
            res = self.col.query(query_embeddings=self.embed([text]), n_results=k, where=where,
                                 include=["documents", "metadatas", "distances"])
        except Exception as e:  # noqa: BLE001  (e.g. no docs match the filter)
            log.debug("similar() query failed: %s", e)
            return []
        out = []
        for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            out.append({"id": i, "summary": d, "similarity": round(1 - float(dist), 3), **m})
        return out

    def symbols(self) -> list[dict]:
        res = self.col.get(include=["metadatas"])
        counts: dict[str, dict] = {}
        for m in res["metadatas"]:
            s = m.get("symbol", "?")
            e = counts.setdefault(s, {"symbol": s, "analyses": 0, "last": ""})
            e["analyses"] += 1
            e["last"] = max(e["last"], m.get("created_at", ""))
        return sorted(counts.values(), key=lambda x: x["last"], reverse=True)

    def delete_symbol(self, symbol: str) -> int:
        ids = self.col.get(where={"symbol": symbol})["ids"]
        if ids:
            self.col.delete(ids=ids)
        return len(ids)


# ---------------------------------------------------------------- feedback loop

def evaluate_past_calls(past: list[dict], df: pd.DataFrame) -> dict:
    """Check earlier analyses' directional calls against prices that arrived since."""
    closes = df["close"]
    tallies = {"day_trading": [0, 0], "short_term": [0, 0], "long_term": [0, 0]}
    horizons = {"day_trading": 1, "short_term": 5, "long_term": 20}
    details = []
    for a in past:
        try:
            ts = pd.Timestamp(a["last_date"])
        except Exception:  # noqa: BLE001
            continue
        if ts not in closes.index:
            continue
        pos = closes.index.get_loc(ts)
        base = closes.iloc[pos]
        row = {"analysis_id": a["id"], "last_date": a["last_date"], "close_then": round(float(base), 2), "results": {}}
        for tf, h in horizons.items():
            v = a.get(f"{tf}_verdict", "Neutral")
            if "Neutral" in v or pos + h >= len(closes):
                continue
            after = closes.iloc[pos + h]
            went_up = after > base
            correct = went_up == ("Bullish" in v)
            tallies[tf][0] += int(correct)
            tallies[tf][1] += 1
            row["results"][tf] = {"call": v, "move_pct": round(float((after / base - 1) * 100), 2), "correct": bool(correct)}
        if row["results"]:
            details.append(row)
    summary = {tf: {"correct": c, "evaluated": n, "hit_rate": round(c / n, 3) if n else None}
               for tf, (c, n) in tallies.items()}
    return {"by_timeframe": summary, "details": details[:10]}
