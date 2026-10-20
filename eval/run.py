"""Stage 15: score retrieval on eval/questions.jsonl.

Run: python -m eval.run --name step1 --mode dense        # tuning split only (the default)
     python -m eval.run --final --name final             # holdout; do this once, at the very end

Retrieval is src.search.search() in the chosen --mode (dense | hybrid | rerank), no product filter, as --role
(default admin = sees every access level, so numbers stay comparable with the first baseline).
Labels are pages: a question's `relevant` is a list of groups, any page in a group satisfies it.
Recall@k = groups satisfied in the top-k chunks / groups. MRR = 1 / rank of the first chunk whose page is in
any group (0 if none in the top K). Unanswerable questions have no relevant page, so retrieval metrics skip them.

Passage metrics (independent of how the text was chunked): each question's `evidence` lists the verbatim quote that
answers it. A chunk "holds" the evidence if it is from that page and at least half of the quote's word triples occur in it
(so a quote cut by a chunk boundary still counts). p_recall@k = evidence items held by one of the top-k chunks / items;
p_mrr = 1 / rank of the first chunk holding any evidence; ctx_recall = share of evidence items inside the context the
answer step would build from the top `k_context` chunks (parent sections included), the number that decides whether the
LLM can answer at all. Bigger chunks hold evidence more easily, so read them together with `avg_chunk_chars`.
"""
import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from src.access import Principal
from src.llm import load_config

KS = (5, 10)
TYPES = ["error_message", "symptom", "version", "cross_product"]


def page_of(hit):
    """Page id used in questions.jsonl, e.g. 'postgres/mvcc.html' or 'stackoverflow/123'."""
    return f"{hit['source']}/{hit['source_path'].split('/', 1)[1]}"


def recall_at_k(pages, relevant, k):
    top = set(pages[:k])
    return sum(any(p in top for p in group) for group in relevant) / len(relevant)


def reciprocal_rank(pages, relevant):
    wanted = {p for group in relevant for p in group}
    return next((1 / i for i, p in enumerate(pages, 1) if p in wanted), 0.0)


def cover(quote, text):
    """Share of the quote's word triples that occur in `text` (1.0 = the quote is in it word for word)."""
    words = lambda t: re.findall(r"[a-z0-9_]+", t.lower())
    grams = lambda w: {tuple(w[i:i + 3]) for i in range(len(w) - 2)} or {tuple(w)}
    q = grams(words(quote))
    return len(q & grams(words(text))) / len(q) if q else 0.0


def holds(page, text, ev, min_cover=0.5):
    return page == ev["page"] and cover(ev["quote"], text) >= min_cover


def passage_scores(question, hits, ctx_items):
    """p_recall@k, p_mrr and ctx_recall for one question (see the module docstring)."""
    ev = question["evidence"]
    held = [[holds(page_of(h), h["text"], e) for e in ev] for h in hits]
    out = {f"p_recall@{k}": sum(any(row[j] for row in held[:k]) for j in range(len(ev))) / len(ev) for k in KS}
    out["p_mrr"] = next((1 / i for i, row in enumerate(held, 1) if any(row)), 0.0)
    out["ctx_recall"] = sum(any(holds(it["source_path"], it["text"], e) for it in ctx_items) for e in ev) / len(ev)
    return out


def score(question, pages):
    rel = question["relevant"]
    return {**{f"recall@{k}": recall_at_k(pages, rel, k) for k in KS}, "mrr": reciprocal_rank(pages, rel)}


def summarize(rows):
    """rows: per-question result dicts with 'type' and the metrics. Returns {group: {n, metric: mean}}."""
    groups = defaultdict(list)
    for r in rows:
        groups["overall"].append(r)
        groups[r["type"]].append(r)
    keys = [k for k in [f"recall@{k}" for k in KS] + ["mrr", "p_recall@5", "p_recall@10", "p_mrr", "ctx_recall"] if k in rows[0]]
    return {g: {"n": len(rs), **{m: sum(r[m] for r in rs) / len(rs) for m in keys}} for g, rs in groups.items()}


def table(summary):
    lines = ["| Question type | n | Recall@5 | Recall@10 | MRR |", "|---|--:|--:|--:|--:|"]
    for g in ["overall"] + TYPES:
        if g in summary:
            s = summary[g]
            lines.append(f"| {g} | {s['n']} | {s['recall@5']:.3f} | {s['recall@10']:.3f} | {s['mrr']:.3f} |")
    return "\n".join(lines)


def _count(cfg):
    from src.store import client
    return client(cfg).count(cfg["qdrant"]["collection"], exact=True).count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="score the holdout split instead of tune")
    ap.add_argument("--name", required=True, help="result file prefix in eval/results/")
    ap.add_argument("--mode", default=None, help="dense | hybrid | rerank (default: retrieval.mode in config.yaml)")
    ap.add_argument("--collection", default=None, help="Qdrant collection (default: qdrant.collection in config.yaml)")
    ap.add_argument("--embedding", default=None, help="embedding model of the collection (default: models.embedding)")
    ap.add_argument("--embedding-device", default=None, help="device for the question embedding (default: models.device)")
    ap.add_argument("--chunking", default=None, help="label for the result file (default: chunking.strategy)")
    ap.add_argument("--role", default="admin", choices=["public", "member", "admin"],
                    help="default admin: all levels, so numbers stay comparable with the first baseline")
    ap.add_argument("--licenses", default="", help="members only: comma-separated products, e.g. github,kafka")
    ap.add_argument("--k-context", type=int, default=None, help="chunks kept for the answer context (default: retrieval.k_context)")
    ap.add_argument("--max-context-chars", type=int, default=None, help="context budget in characters (default: context.max_context_chars)")
    ap.add_argument("--max-section-chars", type=int, default=None, help="longest parent section used (default: context.max_section_chars)")
    ap.add_argument("--plan", default="none", help="query plan parts to use: none, or a comma list of rewrite,route,hyde (src/query.py)")
    ap.add_argument("--plan-llm", default=None, choices=["local", "groq"], help="which LLM writes the plan (default: query.llm)")
    a = ap.parse_args()

    from src.context import build_context
    from src.search import search, search_plan  # imported late so the metric functions load without Qdrant

    cfg = load_config()
    mode = a.mode or cfg["retrieval"]["mode"]
    if a.collection:
        cfg["qdrant"]["collection"] = a.collection
    if a.embedding:
        cfg["models"]["embedding"] = a.embedding
    if a.embedding_device:
        cfg["models"]["embedding_device"] = a.embedding_device
    for flag, section, key in ((a.k_context, "retrieval", "k_context"), (a.max_context_chars, "context", "max_context_chars"),
                               (a.max_section_chars, "context", "max_section_chars")):
        if flag:
            cfg[section][key] = flag
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    who_label = a.role + (f"[{a.licenses}]" if a.licenses else "")
    chunking = a.chunking or cfg["chunking"]["strategy"]
    split = "holdout" if a.final else "tune"
    questions = [json.loads(line) for line in Path(cfg["paths"]["eval_dir"], "questions.jsonl").open(encoding="utf8")]
    questions = [q for q in questions if q["split"] == split]
    unverified = [q["id"] for q in questions if not q["verified"]]
    if unverified:
        raise SystemExit(f"unverified questions, review them first: {unverified}")

    use = () if a.plan == "none" else tuple(x for x in a.plan.split(",") if x)
    assert set(use) <= {"rewrite", "route", "hyde"}, f"unknown plan part in {a.plan!r}"
    if use:
        from src.query import understand
    rows, skipped, ms, chars, plans = [], [], [], [], []
    for q in questions:
        if not q["relevant"]:
            skipped.append(q["id"])
            continue
        t0 = time.perf_counter()
        if use:
            plan = understand(q["question"], cfg, prefer=a.plan_llm)
            plans.append((q, plan))
            t0 = time.perf_counter()  # search time only; plan time is reported separately
            hits = search_plan(q["question"], plan, k=max(max(KS), cfg["retrieval"]["k_context"]), principal=who, mode=mode, cfg=cfg, use=use)
        else:
            hits = search(q["question"], k=max(max(KS), cfg["retrieval"]["k_context"]), principal=who, mode=mode, cfg=cfg)
        ms.append((time.perf_counter() - t0) * 1000)
        pages = [page_of(h) for h in hits]
        ctx = build_context(hits[:cfg["retrieval"]["k_context"]], who, cfg)
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "top_pages": pages,
                     **score(q, pages), **passage_scores(q, hits, ctx)})
        chars.append(sum(len(h["text"]) for h in hits) / len(hits))

    summary = summarize(rows)
    out = Path(cfg["paths"]["eval_results"])
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{a.name}_{split}"
    # the first question also loads models / builds the BM25 index, so latency is the median, not the mean
    median_ms = sorted(ms)[len(ms) // 2] if ms else 0.0
    plan_stats = {}
    if plans:
        truth = [(set(q["products"]), set(p.products)) for q, p in plans]
        plan_stats = {"plan": a.plan, "plan_llm": a.plan_llm or cfg["query"]["llm"],
                      "plans_from": {x: sum(p.provider == x for _, p in plans) for x in {p.provider for _, p in plans}},
                      "route_exact": round(sum(t == g for t, g in truth) / len(truth), 3),
                      "route_found_all": round(sum(t <= g for t, g in truth) / len(truth), 3),
                      "route_wrong_product": round(sum(bool(g - t) for t, g in truth) / len(truth), 3),
                      "median_plan_s": sorted(p.seconds for _, p in plans)[len(plans) // 2]}
    result = {**plan_stats, "split": split, "mode": mode, "role": who_label, "chunking": chunking, "collection": cfg["qdrant"]["collection"],
              "embedding": cfg["models"]["embedding"], "k_used": max(KS), "k_context": cfg["retrieval"]["k_context"], "max_context_chars": cfg["context"]["max_context_chars"], "max_section_chars": cfg["context"]["max_section_chars"], "median_search_ms": round(median_ms),
              "avg_chunk_chars": round(sum(chars) / len(chars)) if chars else 0,
              "chunks_in_collection": _count(cfg), "skipped_unanswerable": skipped, "summary": summary, "per_question": rows}
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf8")
    passage = ", ".join(f"{k} {summary['overall'][k]:.3f}" for k in ("p_recall@5", "p_recall@10", "p_mrr", "ctx_recall")
                        if k in summary["overall"])
    md = table(summary) + (f"\n\nPassage-level (overall): {passage}. Average chunk: {result['avg_chunk_chars']} characters."
                           if passage else "") + (
        f"\n\nQuery plan {plan_stats['plan']} by {plan_stats['plan_llm']}: routing exact {plan_stats['route_exact']:.3f}, "
        f"found all products {plan_stats['route_found_all']:.3f}, named a wrong product {plan_stats['route_wrong_product']:.3f}, "
        f"median plan time {plan_stats['median_plan_s']} s." if plan_stats else "") + (f"\n\nSplit: {split}. Mode: {mode}. Role: {who_label}. Chunking: {chunking}. "
                           f"Median search time: {median_ms:.0f} ms. "
                           f"Unanswerable questions skipped (no relevant page): {len(skipped)}.\n")
    (out / f"{stem}.md").write_text(md, encoding="utf8")
    print(md)
    print("worst questions (MRR=0):", [r["id"] for r in rows if r["mrr"] == 0])


if __name__ == "__main__":
    main()
