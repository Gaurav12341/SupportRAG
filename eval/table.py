"""Build the README retrieval-results table from eval/results/*.json (never typed by hand).

Run: python -m eval.table            # prints markdown; also writes eval/results/retrieval_steps.md
"""
import json
from pathlib import Path

from src.llm import load_config

# (label, kept?, result file, file to take latency from or None)
ROWS = [
    ("0. Baseline: dense only, fixed 500-token chunks", "-", "baseline_dense_tune", "step1b_fixed_check_tune"),
    ("1. Heading-aware chunks, dense only", "no", "step1_headings_tune", "step1_headings_tune"),
    ("2. Fixed chunks + BM25 merged with RRF (hybrid)", "yes", "step_hybrid_tune", "step_hybrid_tune"),
    ("3. Hybrid + cross-encoder rerank (top 30, keep best 5)", "no", "step_rerank_tune", "step_rerank_tune"),
    ("4a. Hybrid, admin (all levels, all products)", "yes", "access_admin_tune", "access_admin_tune"),
    ("4b. Hybrid, member licensed for all 4 products", "yes", "access_member_all_tune", "access_member_all_tune"),
    ("4c. Hybrid, member licensed for github only", "yes", "access_member_github_tune", "access_member_github_tune"),
    ("4d. Hybrid, public (not logged in)", "yes", "access_public_tune", "access_public_tune"),
    ("Re-test: heading chunks + hybrid (admin)", "-", "retest_headings_hybrid_tune", None),
    ("Re-test: heading chunks + hybrid + rerank (admin)", "-", "retest_headings_rerank_tune", None),
]
TYPES = ["error_message", "symptom", "version", "cross_product"]


def main():
    d = Path(load_config()["paths"]["eval_results"])
    load = lambda n: json.loads((d / f"{n}.json").read_text(encoding="utf8"))  # noqa: E731
    lines = ["| Step | Kept | Recall@5 | Recall@10 | MRR | MRR error_message | MRR symptom | MRR version | "
             "MRR cross_product | Median ms |", "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for label, kept, name, ms_name in ROWS:
        s = load(name)["summary"]
        ms = load(ms_name).get("median_search_ms") if ms_name else None
        o = s["overall"]
        lines.append(f"| {label} | {kept} | {o['recall@5']:.3f} | {o['recall@10']:.3f} | {o['mrr']:.3f} | "
                     + " | ".join(f"{s[t]['mrr']:.3f}" for t in TYPES) + f" | {ms if ms is not None else 'n/a'} |")
    md = "\n".join(lines) + "\n"
    (d / "retrieval_steps.md").write_text(md, encoding="utf8")
    print(md)


if __name__ == "__main__":
    main()
