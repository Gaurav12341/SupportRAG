"""Which question types (and which questions) did a change help?

Run: python -m eval.compare baseline_dense_tune step1_headings_tune
Reads two eval/results/*.json files, prints per-type deltas and every question whose rank or recall changed,
and writes eval/results/compare_<a>_vs_<b>.md.
"""
import json
import sys
from pathlib import Path

from eval.run import TYPES
from src.llm import load_config


def rank(row):
    """Rank of the first correct chunk (None = not in the top 10)."""
    return round(1 / row["mrr"]) if row["mrr"] else None


def compare(a, b):
    """a, b: parsed result files. Returns (markdown, changes) where changes lists per-question movements."""
    ra = {r["id"]: r for r in a["per_question"]}
    rb = {r["id"]: r for r in b["per_question"]}
    lines = ["| Question type | n | dRecall@5 | dRecall@10 | dMRR |", "|---|--:|--:|--:|--:|"]
    for g in ["overall"] + TYPES:
        if g in a["summary"] and g in b["summary"]:
            x, y = a["summary"][g], b["summary"][g]
            lines.append(f"| {g} | {y['n']} | {y['recall@5'] - x['recall@5']:+.3f} | "
                         f"{y['recall@10'] - x['recall@10']:+.3f} | {y['mrr'] - x['mrr']:+.3f} |")
    changes = []
    for qid in ra:
        if qid not in rb:
            continue
        x, y = ra[qid], rb[qid]
        if (rank(x), x["recall@5"], x["recall@10"]) != (rank(y), y["recall@5"], y["recall@10"]):
            better = (y["mrr"], y["recall@10"], y["recall@5"]) > (x["mrr"], x["recall@10"], x["recall@5"])
            changes.append((qid, x["type"], rank(x), rank(y), x["recall@10"], y["recall@10"], better))
    helped = [c for c in changes if c[6]]
    hurt = [c for c in changes if not c[6]]
    lines += ["", f"Questions helped: {len(helped)}, hurt: {len(hurt)}, unchanged: {len(ra) - len(changes)}.", ""]
    lines += ["| Question | Type | First-hit rank before | after | Recall@10 before | after |", "|---|---|--:|--:|--:|--:|"]
    for qid, t, ra_, rb_, r1, r2, better in sorted(changes, key=lambda c: (not c[6], c[0])):
        mark = "helped" if better else "hurt"
        lines.append(f"| {qid} ({mark}) | {t} | {ra_ or 'miss'} | {rb_ or 'miss'} | {r1:.2f} | {r2:.2f} |")
    return "\n".join(lines) + "\n", changes


def main():
    ea, eb = sys.argv[1], sys.argv[2]
    d = Path(load_config()["paths"]["eval_results"])
    a, b = (json.loads((d / f"{n}.json").read_text(encoding="utf8")) for n in (ea, eb))
    md, _ = compare(a, b)
    (d / f"compare_{ea}_vs_{eb}.md").write_text(f"{ea} -> {eb}\n\n" + md, encoding="utf8")
    print(f"{ea} -> {eb}\n\n{md}")


if __name__ == "__main__":
    main()
