"""Stage 15 (answers): run the answer step on the test questions with the verifier off and on.

Run: python -m eval.answer --name answer_v1            # tuning split (default)
     python -m eval.answer --final --name answer_final # holdout; once, at the very end

Each question is retrieved and generated ONCE; the same draft is then finalized with verify=False and verify=True, so
the two columns differ only by the verifier. Role defaults to admin (all levels), like the retrieval eval.

Measures (all counted from the run, nothing typed in by hand):
  steps shown            steps in the answers that reach the user
  unsupported steps      shown steps with no valid cited chunk, or whose cited text does not entail them (NLI score
                         below thresholds.min_nli_entailment). This is the verifier's own yardstick, so with the
                         verifier on it is 0 by construction; it is the OFF column that carries information.
  steps with ungrounded  an independent check, not NLI: shown steps whose inline `commands` / code lines contain a
  command words          word that appears nowhere in the retrieved docs (placeholders like <pod> are ignored)
  unanswerable refused   of the questions the docs cannot answer, how many got "No documented fix found."
  answerable refused     answerable questions that were refused anyway (the cost of the verifier)
"""
import argparse
import copy
import json
import re
import statistics
import time
from pathlib import Path

from src.access import Principal
from src.answer import Draft, answer_cfg, finalize, generate
from src.context import build_context
from src.llm import LLMClient, load_config


def command_words(step_text):
    """Words inside inline code spans of a step, minus placeholders."""
    words = []
    for span in re.findall(r"`([^`\n]+)`", step_text):
        words += [w for w in re.split(r"\s+", span) if re.search(r"[A-Za-z]", w) and not re.search(r"[<>{}$\[\]]", w)]
    return words


def ungrounded(step_text, context_text):
    low = context_text.lower()
    return [w for w in command_words(step_text) if w.strip("`'\",;.()").lower() not in low]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="score the holdout split instead of tune")
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", default="admin", choices=["public", "member", "admin"])
    ap.add_argument("--licenses", default="")
    ap.add_argument("--collection", default=None, help="Qdrant collection (default: qdrant.collection in config.yaml)")
    ap.add_argument("--embedding", default=None, help="embedding model of that collection (default: models.embedding)")
    ap.add_argument("--embedding-device", default=None, help="device for the question embedding (default: models.device)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (smoke test)")
    a = ap.parse_args()

    from src.search import search

    cfg = answer_cfg(load_config())
    cfg["verify"] = {**cfg["verify"], "method": "nli"}  # this eval measures the NLI verifier (Phase 1-2 numbers); the LLM check is measured by eval.accuracy
    if a.collection:
        cfg["qdrant"]["collection"] = a.collection
    if a.embedding:
        cfg["models"]["embedding"] = a.embedding
    if a.embedding_device:
        cfg["models"]["embedding_device"] = a.embedding_device
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    split = "holdout" if a.final else "tune"
    qs = [json.loads(line) for line in Path(cfg["paths"]["eval_dir"], "questions.jsonl").open(encoding="utf8")]
    qs = [q for q in qs if q["split"] == split]
    if unverified := [q["id"] for q in qs if not q["verified"]]:
        raise SystemExit(f"unverified questions, review them first: {unverified}")
    if a.limit:
        qs = qs[:a.limit]
    llm, th = LLMClient(cfg["llm"]), cfg["thresholds"]["min_nli_entailment"]

    rows = []
    for q in qs:
        t0 = time.perf_counter()
        hits = search(q["question"], k=cfg["retrieval"]["k_context"], principal=who, cfg=cfg)
        items = build_context(hits, who, cfg)
        draft, refused, provider = generate(q["question"], items, cfg, llm) if items else (Draft("not_found", "none", "", "", []), True, "")
        steps = draft.steps
        gen_s = time.perf_counter() - t0
        ctx_text = "\n".join(it["text"] for it in items)
        row = {"id": q["id"], "type": q["type"], "answerable": q["expected"] == "answer", "provider": provider,
               "drafted_steps": len(steps), "seconds": round(gen_s, 1)}
        for mode, verify in (("off", False), ("on", True)):
            ans = finalize(q["question"], items, copy.deepcopy(draft), refused, provider, who, cfg, verify)
            scored = ans.checked if verify else None
            row[mode] = {
                "refused": ans.refused, "blocked": ans.blocked, "steps_shown": len(ans.steps),
                "steps": [{"text": s.text, "cited": s.cited, "bad_cites": s.bad_cites,
                           "entailment": s.entailment, "copied": s.copied, "warnings": s.warnings,
                           "ungrounded_words": ungrounded(s.text, ctx_text)} for s in ans.steps],
            }
            if scored:
                row["scored_steps"] = [{"text": s.text, "cited": s.cited, "bad_cites": s.bad_cites,
                                        "entailment": round(s.entailment, 3), "copied": round(s.copied, 3), "supported": s.supported} for s in scored]
        # unsupported steps in the OFF answer are judged with the scores the ON run computed for the same steps
        by_text = {s["text"]: s for s in row.get("scored_steps", [])}
        for st in row["off"]["steps"]:
            sc = by_text.get(st["text"])
            st["unsupported"] = (not st["cited"] or bool(st["bad_cites"])) if sc is None else not sc["supported"]
        rows.append(row)
        print(f"{q['id']:8} {q['expected']:7} off: {'refused' if row['off']['refused'] else str(row['off']['steps_shown']) + ' steps'}"
              f" | on: {'refused' if row['on']['refused'] else str(row['on']['steps_shown']) + ' steps'} ({provider or '-'}, {gen_s:.0f}s)")

    # ---- summary ----
    ans_rows, un_rows = [r for r in rows if r["answerable"]], [r for r in rows if not r["answerable"]]

    def agg(mode):
        shown = [s for r in ans_rows for s in r[mode]["steps"]]
        return {
            "answerable_questions": len(ans_rows),
            "answerable_refused": sum(r[mode]["refused"] for r in ans_rows),
            "steps_shown": len(shown),
            "steps_unsupported": sum(s.get("unsupported", False) for s in shown),
            "steps_no_valid_citation": sum((not s["cited"]) or bool(s["bad_cites"]) for s in shown),
            "steps_ungrounded_command_words": sum(bool(s["ungrounded_words"]) for s in shown),
            "steps_with_danger_warning": sum(bool(s["warnings"]) for s in shown),
            "unanswerable_questions": len(un_rows),
            "unanswerable_refused": sum(r[mode]["refused"] for r in un_rows),
            "answers_blocked_secrets": sum(bool(r[mode]["blocked"]) for r in rows),
        }

    summary = {"off": agg("off"), "on": agg("on"), "split": split, "role": a.role + (f"[{a.licenses}]" if a.licenses else ""),
               "collection": cfg["qdrant"]["collection"], "embedding": cfg["models"]["embedding"], "min_nli_entailment": th, "min_supported_fraction": cfg["thresholds"]["min_supported_fraction"],
               "providers": {p or "none": sum(r["provider"] == p for r in rows) for p in {r["provider"] for r in rows}},
               "median_generate_s": statistics.median(r["seconds"] for r in rows) if rows else 0}
    off, on = summary["off"], summary["on"]
    md = "\n".join([
        "| | Verifier off | Verifier on |", "|---|--:|--:|",
        f"| Steps shown (answerable questions) | {off['steps_shown']} | {on['steps_shown']} |",
        f"| Unsupported steps shown | {off['steps_unsupported']} | {on['steps_unsupported']} |",
        f"| Steps with no valid citation | {off['steps_no_valid_citation']} | {on['steps_no_valid_citation']} |",
        f"| Steps with a command word not in the docs | {off['steps_ungrounded_command_words']} | {on['steps_ungrounded_command_words']} |",
        f"| Unanswerable questions refused | {off['unanswerable_refused']} of {off['unanswerable_questions']} | {on['unanswerable_refused']} of {on['unanswerable_questions']} |",
        f"| Answerable questions refused | {off['answerable_refused']} of {off['answerable_questions']} | {on['answerable_refused']} of {on['answerable_questions']} |",
        f"| Answers blocked (secrets / personal data) | {off['answers_blocked_secrets']} | {on['answers_blocked_secrets']} |",
        f"\nSplit: {split}. Role: {summary['role']}. NLI threshold {th}, min supported fraction "
        f"{cfg['thresholds']['min_supported_fraction']}. Answer provider per question: {summary['providers']}. "
        f"Median generation time {summary['median_generate_s']} s.\n"])
    out = Path(cfg["paths"]["eval_results"])
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.name}_{split}.json").write_text(json.dumps({"summary": summary, "per_question": rows}, indent=2, ensure_ascii=False), encoding="utf8")
    (out / f"{a.name}_{split}.md").write_text(md, encoding="utf8")
    print("\n" + md)


if __name__ == "__main__":
    main()
