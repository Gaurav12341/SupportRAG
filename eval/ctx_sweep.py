"""Table of the context-size sweep (Phase 2c): how much of the labelled evidence ends up in the context the writer reads.

Run (after `python -m eval.run --name ctx_k8_c10000_s2000 --k-context 8 --max-context-chars 10000 --max-section-chars 2000` and so on):
    python -m eval.ctx_sweep            # reads eval/results/ctx_k*_tune.json, writes eval/results/context_sweep.md
No LLM is involved: ctx_recall is the share of evidence quotes found inside the built context (passage level, strict).
"""
import json
from pathlib import Path

from src.llm import load_config


def main():
    d = Path(load_config()["paths"]["eval_results"])
    rows = []
    for f in sorted(d.glob("ctx_k*_tune.json")):
        r = json.loads(f.read_text(encoding="utf8"))
        if "k_context" in r:
            s = r["summary"]
            rows.append((r["k_context"], r["max_context_chars"], r["max_section_chars"], s["overall"]["ctx_recall"], s["cross_product"]["ctx_recall"]))
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    md = ["| k_context | max_context_chars | max_section_chars | ctx_recall (all) | ctx_recall (cross_product) |", "|--:|--:|--:|--:|--:|"]
    md += [f"| {k} | {c} | {s} | {a:.3f} | {x:.3f} |" for k, c, s, a, x in rows]
    (d / "context_sweep.md").write_text("\n".join(md) + "\n", encoding="utf8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
