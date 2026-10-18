"""Stage 15: score retrieval on eval/questions.jsonl.

Run: python -m eval.run --name step1 --mode dense        # tuning split only (the default)
     python -m eval.run --final --name final             # holdout; do this once, at the very end

Retrieval is src.search.search() in the chosen --mode (dense | hybrid | rerank), no product filter, as --role
(default admin = sees every access level, so numbers stay comparable with the first baseline).
Labels are pages: a question's `relevant` is a list of groups, any page in a group satisfies it.
Recall@k = groups satisfied in the top-k chunks / groups. MRR = 1 / rank of the first chunk whose page is in
any group (0 if none in the top K). Unanswerable questions have no relevant page, so retrieval metrics skip them.
"""
import argparse
import json
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


def score(question, pages):
    rel = question["relevant"]
    return {**{f"recall@{k}": recall_at_k(pages, rel, k) for k in KS}, "mrr": reciprocal_rank(pages, rel)}


def summarize(rows):
    """rows: per-question result dicts with 'type' and the metrics. Returns {group: {n, metric: mean}}."""
    groups = defaultdict(list)
    for r in rows:
        groups["overall"].append(r)
        groups[r["type"]].append(r)
    keys = [f"recall@{k}" for k in KS] + ["mrr"]
    return {g: {"n": len(rs), **{m: sum(r[m] for r in rs) / len(rs) for m in keys}} for g, rs in groups.items()}


def table(summary):
    lines = ["| Question type | n | Recall@5 | Recall@10 | MRR |", "|---|--:|--:|--:|--:|"]
    for g in ["overall"] + TYPES:
        if g in summary:
            s = summary[g]
            lines.append(f"| {g} | {s['n']} | {s['recall@5']:.3f} | {s['recall@10']:.3f} | {s['mrr']:.3f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="score the holdout split instead of tune")
    ap.add_argument("--name", required=True, help="result file prefix in eval/results/")
    ap.add_argument("--mode", default=None, help="dense | hybrid | rerank (default: retrieval.mode in config.yaml)")
    ap.add_argument("--collection", default=None, help="Qdrant collection (default: qdrant.collection in config.yaml)")
    ap.add_argument("--chunking", default=None, help="label for the result file (default: chunking.strategy)")
    ap.add_argument("--role", default="admin", choices=["public", "member", "admin"],
                    help="default admin: all levels, so numbers stay comparable with the first baseline")
    ap.add_argument("--licenses", default="", help="members only: comma-separated products, e.g. github,kafka")
    a = ap.parse_args()

    from src.search import search  # imported late so the metric functions load without Qdrant

    cfg = load_config()
    mode = a.mode or cfg["retrieval"]["mode"]
    if a.collection:
        cfg["qdrant"]["collection"] = a.collection
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    who_label = a.role + (f"[{a.licenses}]" if a.licenses else "")
    chunking = a.chunking or cfg["chunking"]["strategy"]
    split = "holdout" if a.final else "tune"
    questions = [json.loads(line) for line in Path(cfg["paths"]["eval_dir"], "questions.jsonl").open(encoding="utf8")]
    questions = [q for q in questions if q["split"] == split]
    unverified = [q["id"] for q in questions if not q["verified"]]
    if unverified:
        raise SystemExit(f"unverified questions, review them first: {unverified}")

    rows, skipped, ms = [], [], []
    for q in questions:
        if not q["relevant"]:
            skipped.append(q["id"])
            continue
        t0 = time.perf_counter()
        hits = search(q["question"], k=max(KS), principal=who, mode=mode, cfg=cfg)
        ms.append((time.perf_counter() - t0) * 1000)
        pages = [page_of(h) for h in hits]
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "top_pages": pages,
                     **score(q, pages)})

    summary = summarize(rows)
    out = Path(cfg["paths"]["eval_results"])
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{a.name}_{split}"
    # the first question also loads models / builds the BM25 index, so latency is the median, not the mean
    median_ms = sorted(ms)[len(ms) // 2] if ms else 0.0
    result = {"split": split, "mode": mode, "role": who_label, "chunking": chunking, "collection": cfg["qdrant"]["collection"],
              "k_used": max(KS), "median_search_ms": round(median_ms), "skipped_unanswerable": skipped, "summary": summary, "per_question": rows}
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf8")
    md = table(summary) + (f"\n\nSplit: {split}. Mode: {mode}. Role: {who_label}. Chunking: {chunking}. "
                           f"Median search time: {median_ms:.0f} ms. "
                           f"Unanswerable questions skipped (no relevant page): {len(skipped)}.\n")
    (out / f"{stem}.md").write_text(md, encoding="utf8")
    print(md)
    print("worst questions (MRR=0):", [r["id"] for r in rows if r["mrr"] == 0])


if __name__ == "__main__":
    main()
