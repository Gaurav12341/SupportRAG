"""The online pipeline end to end, as the API and the UI call it: input safety -> rewrite -> product -> search -> answer.

    python -m src.pipeline "psql says password authentication failed" --role member --licenses postgres

`ask()` never raises for a bad question (it returns status "blocked"); LLM outages surface as exceptions for the caller to turn into
a "service unavailable" message. Retrieved chunks that look like injected instructions are left out before the writer sees them.
"""
import argparse
import logging
import sys
from dataclasses import dataclass, field

from src.access import PRODUCTS, Principal
from src.answer import Answer, answer, answer_cfg
from src.guard import check_input, scan_chunk
from src.llm import LLMClient, load_config
from src.rewrite import standalone, trim_history

log = logging.getLogger("supportrag.llm")


@dataclass
class Result:
    status: str                     # answered | refused | blocked
    message: str = ""               # what to tell the user when blocked or refused
    question: str = ""              # the question actually searched (after the rewrite)
    rewritten: bool = False
    products: list = field(default_factory=list)   # products the question is about, as detected
    product_filter: str = ""        # product the search was restricted to ("" = all)
    dropped_chunks: list = field(default_factory=list)  # [(chunk_id, rule)] left out as injection-like
    block_rule: str = ""
    answer: Answer | None = None


def detect_products(question, cfg, llm):
    """Products named by the query plan (one cached call on the rewrite model's bucket); [] if unknown or the LLMs are down."""
    from src.query import understand
    r = cfg["rewrite"]
    return understand(question, cfg, llm, prefer=r["llm"], model=r["model"]).products


def ask(question, principal=None, history=None, product=None, cfg=None, llm=None, verify=True):
    cfg = cfg or load_config()
    principal = principal or Principal.public()
    if product and product not in PRODUCTS:
        raise ValueError(f"unknown product {product!r}; known products: {list(PRODUCTS)}")
    verdict = check_input(question, cfg)
    if not verdict.blocked:  # earlier questions are user input too
        verdict = next((v for v in (check_input(t["q"], cfg) for t in trim_history(history, cfg)) if v.blocked), verdict)
    if verdict.blocked:
        log.info("INPUT BLOCKED rule=%s", verdict.rule)
        return Result("blocked", verdict.message, question, block_rule=verdict.rule)

    llm = llm or LLMClient(cfg["llm"])
    text, rewritten = standalone(question, history, cfg, llm)
    if rewritten and (v := check_input(text, cfg)).blocked:  # the rewrite must pass the same checks
        text, rewritten = question, False
    products = detect_products(text, cfg, llm) if cfg["rewrite"]["detect_product"] else []
    if not product and cfg["rewrite"]["route_product"] and len(products) == 1:
        product = products[0]

    from src.search import search
    acfg = answer_cfg(cfg)
    hits = search(text, k=acfg["retrieval"]["k_context"], product=product, principal=principal, cfg=acfg)
    dropped = []
    if cfg["input"]["scan_chunks"]:
        for h in hits:
            if rule := scan_chunk(h["text"]):
                dropped.append((h["chunk_id"], rule))
        if dropped:
            log.warning("CHUNK DROPPED as injection-like: %s", dropped)
            bad = {c for c, _ in dropped}
            hits = [h for h in hits if h["chunk_id"] not in bad]
    ans = answer(text, principal, product, verify, cfg, llm, hits=hits)
    return Result("refused" if ans.refused else "answered", ans.reason if ans.refused else "", text, rewritten, products, product or "", dropped, "", ans)


def to_dict(res, snippet=700):
    """JSON-friendly form for the API: the answer with citations, the sources, and the retrieved passages."""
    out = {"status": res.status, "message": res.message, "question_used": res.question, "rewritten": res.rewritten,
           "products": res.products, "product_filter": res.product_filter, "dropped_chunks": res.dropped_chunks, "block_rule": res.block_rule}
    a = res.answer
    if a:
        out |= {"kind": a.kind, "coverage": a.coverage, "provider": a.provider, "verified_by": a.verified_by, "summary": a.summary,
                "partial_note": a.partial, "summary_warnings": a.summary_warnings,
                "points": [{"text": s.text, "cited": s.cited, "warnings": s.warnings} for s in a.steps],
                "sources": [{"chunk_id": it["chunk_id"], "title": it["title"], "url": it["url"], "product": it["product"]} for it in a.sources],
                "passages": [{"label": it["label"], "chunk_id": it["chunk_id"], "title": it["title"], "url": it["url"], "product": it["product"],
                              "access_level": it["access_level"], "text": it["text"][:snippet]} for it in a.context]}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--role", default="public", choices=["public", "member", "admin"])
    ap.add_argument("--licenses", default="")
    ap.add_argument("--product", choices=PRODUCTS)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    res = ask(a.question, who, product=a.product)
    print(res.message or res.answer.render(), f"\n\n(status {res.status}; products {res.products}; dropped chunks {res.dropped_chunks})")
