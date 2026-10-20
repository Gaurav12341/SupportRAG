"""Side-by-side table of eval/run.py results, for the chunking / embedding experiments.

Run: python -m eval.variants out_name label=result_name [label=result_name ...]
     e.g. python -m eval.variants chunk_embed_hybrid "fixed 500=base_hybrid" "recursive 500=rec500_hybrid"
Reads eval/results/<result_name>_tune.json and writes eval/results/<out_name>.md. Nothing is typed in by hand.
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
COLS = [
        ("recall@10", "Page R@10", "{:.3f}"), ("mrr", "Page MRR", "{:.3f}"),
        ("p_recall@5", "Passage R@5", "{:.3f}"), ("p_recall@10", "Passage R@10", "{:.3f}"), ("p_mrr", "Passage MRR", "{:.3f}"),
        ("ctx_recall", "Answer in context", "{:.3f}"), ("route_exact", "Product routing", "{:.3f}"), ("median_plan_s", "Plan s", "{:.2f}")]


def row(label, name):
    d = json.loads((RESULTS / f"{name}_tune.json").read_text(encoding="utf8"))
    flat = {**d, **d["summary"]["overall"]}
    return f"| {label} | " + " | ".join(fmt.format(flat[k]) if k in flat else "n/a" for k, _, fmt in COLS) + " |"


def main():
    out, pairs = sys.argv[1], [a.split("=", 1) for a in sys.argv[2:]]
    lines = ["| Variant | " + " | ".join(h for _, h, _ in COLS) + " |", "|---|" + "--:|" * len(COLS)]
    lines += [row(label, name) for label, name in pairs]
    text = "\n".join(lines) + "\n"
    (RESULTS / f"{out}.md").write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
