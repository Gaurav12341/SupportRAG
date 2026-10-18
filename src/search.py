"""Stages 8-11: embed the question, retrieve (meaning + keyword search), merge with RRF, rerank.

Every stage sees only chunks the caller (a `Principal`, see src/access.py) may read: the access filter is part
of the Qdrant query (dense) and is applied before BM25 scores are ranked, so a chunk the caller cannot read never
reaches RRF or the reranker. No principal = public. Unknown roles/products raise an error (fail closed).

Run: python -m src.search "pod stuck in CrashLoopBackOff" --role member --licenses kubernetes,github
"""
import argparse
import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

from src.access import Principal
from src.embed import embed_query
from src.llm import load_config
from src.store import check_model, client

MODES = ("dense", "hybrid", "rerank")  # dense only | + BM25 merged with RRF | + cross-encoder rerank


@lru_cache(maxsize=4)
def _default_client(url):
    """One client per process, so the BM25 index (cached per client) is built once, not on every search."""
    return client({"qdrant": {"url": url}})


# ---------- BM25 (keyword search) ----------

def tokenize(text):
    return re.findall(r"\w+", text.lower())


class BM25Index:
    """BM25 over every chunk in the collection (title + text). Built once per process from Qdrant's payloads,
    so it always matches what is indexed. Access and product filtering happen before ranking."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.bm25 = BM25Okapi([tokenize(p.get("title", "") + " " + p["text"]) for p in payloads])

    def search(self, question, k, principal, cfg, product=None):
        scores = self.bm25.get_scores(tokenize(question))
        ok = [i for i, p in enumerate(self.payloads)
              if principal.allows(p, cfg) and (product is None or p.get("product") == product)]
        ranked = sorted(ok, key=lambda i: scores[i], reverse=True)[:k]
        return [{"score": float(scores[i]), **self.payloads[i]} for i in ranked if scores[i] > 0]


_bm25_cache = {}


def bm25_index(qc, collection):
    n = qc.count(collection, exact=True).count
    key = (id(qc), collection)
    if key not in _bm25_cache or len(_bm25_cache[key].payloads) != n:
        payloads, offset = [], None
        while True:
            points, offset = qc.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
            payloads += [p.payload for p in points]
            if offset is None:
                break
        _bm25_cache[key] = BM25Index(payloads)
    return _bm25_cache[key]


# ---------- RRF (merge) ----------

def rrf(rankings, rrf_k=60):
    """Reciprocal Rank Fusion. `rankings`: lists of hits, best first. A chunk's score is the sum of
    1 / (rrf_k + rank) over the lists it appears in. Returns merged hits, best first."""
    fused, hits = {}, {}
    for ranking in rankings:
        for rank, h in enumerate(ranking, 1):
            fused[h["chunk_id"]] = fused.get(h["chunk_id"], 0.0) + 1.0 / (rrf_k + rank)
            hits.setdefault(h["chunk_id"], h)
    return [{**hits[c], "score": s} for c, s in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]


# ---------- rerank ----------

@lru_cache(maxsize=1)
def _reranker(name, device):
    from sentence_transformers import CrossEncoder
    # models are pre-downloaded by scripts/download_models.py; stay offline
    return CrossEncoder(name, device=device, max_length=512, local_files_only=True)


def rerank(question, hits, cfg):
    """Re-score (question, chunk text) pairs with the cross-encoder; best first."""
    if not hits:
        return []
    m = _reranker(cfg["models"]["reranker"], cfg["models"]["device"])
    scores = m.predict([(question, h["text"]) for h in hits], batch_size=16, show_progress_bar=False)
    return [{**h, "score": float(s)} for h, s in sorted(zip(hits, scores), key=lambda t: t[1], reverse=True)]


# ---------- the search ----------

def search(question, k=None, product=None, principal=None, mode=None, cfg=None, qc=None):
    """Top-k chunks (score + payload) the principal may read (default: public). Raises EmbeddingModelMismatch if
    the index was built with a different embedding model than config.yaml names, ValueError for an unknown mode.

    mode "dense":  meaning search only.
    mode "hybrid": meaning + BM25 keyword search, merged with RRF.
    mode "rerank": hybrid, then the top `k_rerank_in` candidates re-scored by the cross-encoder.
    k defaults to `k_context` (what the answer step gets) for rerank mode and `k_dense` otherwise."""
    cfg = cfg or load_config()
    qc = qc or _default_client(cfg["qdrant"]["url"])
    check_model(qc, cfg)
    r = cfg["retrieval"]
    mode = mode or r["mode"]
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; use one of {MODES}")
    principal = principal or Principal.public()
    k = k or (r["k_context"] if mode == "rerank" else r["k_dense"])
    collection = cfg["qdrant"]["collection"]

    res = qc.query_points(collection, query=embed_query(question, cfg).tolist(),
                          query_filter=principal.qdrant_filter(cfg, product), limit=max(r["k_dense"], k), with_payload=True)
    dense = [{"score": p.score, **p.payload} for p in res.points]
    if mode == "dense":
        return dense[:k]

    keyword = bm25_index(qc, collection).search(question, r["k_bm25"], principal, cfg, product)
    merged = rrf([dense, keyword], r["rrf_k"])
    if mode == "hybrid":
        return merged[:k]
    return rerank(question, merged[:r["k_rerank_in"]], cfg)[:k]


def show(hits):
    for i, h in enumerate(hits, 1):
        snippet = " ".join(h["text"].split())[:160]
        print(f"{i}. [{h['score']:.3f}] {h['product']}/{h['doc_type']}/{h['access_level']}  {h['title']}\n"
              f"   {h['url']}\n   {snippet}...")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--product", choices=["kubernetes", "postgres", "kafka", "github"])
    ap.add_argument("--role", default="public", choices=["public", "member", "admin"])
    ap.add_argument("--licenses", default="", help="members only: comma-separated products, e.g. github,kafka")
    ap.add_argument("--mode", choices=MODES)
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    show(search(a.question, a.k, a.product, who, a.mode))
