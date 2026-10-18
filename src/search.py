"""Stage 8-9 (basic): embed the question, return the top-k chunks, optionally for one product.

Run: python -m src.search "pod stuck in CrashLoopBackOff" --product kubernetes
"""
import argparse

from qdrant_client import models

from src.embed import embed_query
from src.llm import load_config
from src.store import check_model, client


def search(question, k=None, product=None, cfg=None, qc=None):
    """Return the top-k chunks as dicts (score + payload). Raises EmbeddingModelMismatch if the index
    was built with a different embedding model than config.yaml names."""
    cfg = cfg or load_config()
    qc = qc or client(cfg)
    check_model(qc, cfg)
    k = k or cfg["retrieval"]["k_dense"]
    flt = (models.Filter(must=[models.FieldCondition(key="product", match=models.MatchValue(value=product))])
           if product else None)
    res = qc.query_points(cfg["qdrant"]["collection"], query=embed_query(question, cfg).tolist(),
                          query_filter=flt, limit=k, with_payload=True)
    return [{"score": p.score, **p.payload} for p in res.points]


def show(hits):
    for i, h in enumerate(hits, 1):
        snippet = " ".join(h["text"].split())[:160]
        print(f"{i}. [{h['score']:.3f}] {h['product']}/{h['doc_type']}/{h['access_level']}  {h['title']}\n"
              f"   {h['url']}\n   {snippet}...")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--product", choices=["kubernetes", "postgres", "kafka", "github"])
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    show(search(a.question, a.k, a.product))
