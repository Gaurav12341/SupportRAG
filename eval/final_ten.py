"""The 10 original holdout questions (never used before Phase 5), read out of the one holdout run: `python -m eval.final_ten`.

No new LLM calls: eval/results/accuracy_final_holdout.json is the single Phase 5 run of the frozen pipeline over all 38 holdout questions;
this prints the results of the 10 questions that were in the holdout from the start (the other 28 are new questions added to it).
"""
import json
from pathlib import Path

from eval.stats import with_ci

OLD = ["err-02", "err-06", "err-10", "sym-04", "sym-09", "ver-03", "ver-05", "x-03", "none-01", "none-06"]


def main():
    d = json.loads(Path("eval/results/accuracy_final_holdout.json").read_text(encoding="utf8"))
    rows = {r["id"]: r for r in d["per_question"]}
    got = [rows[i] for i in OLD]
    ok = sum(r["on"]["judge"]["correct"] for r in got)
    lines = [f"**The 10 original holdout questions: {with_ci(ok, len(got))}** (read from `accuracy_final_holdout.json`, one run, frozen pipeline).", "",
             "| Question | Type | Shown answer | Category |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['type']} | {r['on']['judge']['verdict']} | {r['category']} |" for r in got]
    md = "\n".join(lines) + "\n"
    Path("eval/results/final_original10.md").write_text(md, encoding="utf8")
    print(md)


if __name__ == "__main__":
    main()
