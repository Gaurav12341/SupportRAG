"""Compare two accuracy runs on the same questions: headline, verifier-off accuracy, failure buckets, per-question changes.
Also used for the run-to-run spread (the same pipeline, answers sampled twice).

Run: python -m eval.spread baseline baseline_run2          # reads eval/results/accuracy_<name>_tune.json
     python -m eval.spread baseline p2 --dev                # only the dev subset (needs the questions both runs have)
Writes eval/results/spread_<a>_vs_<b>[_dev].md
"""
import json
import sys
from collections import Counter
from pathlib import Path

from eval.accuracy import CATEGORIES
from eval.stats import with_ci
from src.llm import load_config


def compare(a_rows: list, b_rows: list) -> dict:
    """Per-question outcome of two runs (verifier on): correct or not."""
    a = {r["id"]: r["on"]["judge"]["correct"] for r in a_rows}
    b = {r["id"]: r["on"]["judge"]["correct"] for r in b_rows}
    ids = sorted(set(a) & set(b))
    return {"n": len(ids), "correct_a": sum(a[i] for i in ids), "correct_b": sum(b[i] for i in ids),
            "same_outcome": sum(a[i] == b[i] for i in ids), "both_correct": sum(a[i] and b[i] for i in ids),
            "only_a": sum(a[i] and not b[i] for i in ids), "only_b": sum(b[i] and not a[i] for i in ids)}


def main(name_a: str, name_b: str, dev: bool = False, split: str = "tune"):
    cfg = load_config()
    out = Path(cfg["paths"]["eval_results"])
    load = lambda n: json.loads((out / f"accuracy_{n}_{split}.json").read_text(encoding="utf8"))["per_question"]  # noqa: E731
    a_rows, b_rows = load(name_a), load(name_b)
    if dev:
        dev_ids = {q["id"] for q in map(json.loads, Path(cfg["paths"]["eval_dir"], "questions.jsonl").open(encoding="utf8")) if q.get("dev")}
        a_rows, b_rows = [r for r in a_rows if r["id"] in dev_ids], [r for r in b_rows if r["id"] in dev_ids]
    c = compare(a_rows, b_rows)
    ca, cb = c["correct_a"], c["correct_b"]
    off = lambda rows: sum(r["off"]["judge"]["correct"] for r in rows)  # noqa: E731
    cat = lambda rows: Counter(r["category"] for r in rows)  # noqa: E731
    ka, kb = cat(a_rows), cat(b_rows)
    md = "\n".join([
        f"Same questions ({c['n']}{', the dev subset' if dev else ''}, {split} split), two runs, verifier on:", "",
        f"- `{name_a}`: {with_ci(ca, c['n'])}; verifier off: {with_ci(off(a_rows), c['n'])}",
        f"- `{name_b}`: {with_ci(cb, c['n'])}; verifier off: {with_ci(off(b_rows), c['n'])}",
        f"- difference: {abs(ca - cb)} questions ({100 * abs(ca - cb) / c['n']:.1f} points)",
        f"- same outcome (correct or not) on {c['same_outcome']} of {c['n']} questions; correct in both {c['both_correct']}, "
        f"only in `{name_a}` {c['only_a']}, only in `{name_b}` {c['only_b']}", "",
        f"| Failure category (verifier on) | `{name_a}` | `{name_b}` |", "|---|--:|--:|"]
        + [f"| {k} | {ka.get(k, 0)} | {kb.get(k, 0)} |" for k in CATEGORIES] + [""])
    (out / f"spread_{name_a}_vs_{name_b}{'_dev' if dev else ''}.md").write_text(md, encoding="utf8")
    print(md)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], dev="--dev" in sys.argv)
