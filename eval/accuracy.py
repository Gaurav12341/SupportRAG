"""Stage 15 (answers): end-to-end ACCURACY of the whole answer pipeline, the user's metric.

    accuracy = (answerable questions answered correctly + unanswerable questions refused) / all questions

Run: python -m eval.accuracy --name baseline                 # tuning split (all of it)
     python -m eval.accuracy --name baseline_dev --dev       # the fixed 40-question dev subset of tune
     python -m eval.accuracy --final --name final            # holdout; once, at the very end of the project

Per question: search -> context -> generate -> verifier -> output safety (the real pipeline, as configured in config.yaml),
then the judge (eval/judge.py) grades the answer the user would see. The same draft is also finalized with the verifier OFF and
judged, which gives the "verifier off" column and the verifier_false_refusal count. Every LLM call is cached on disk
(data/cache), so a rerun is free; if a Groq daily quota runs out the run stops cleanly and the same command resumes it later.

Failure categories for every question that is not correct (first match wins):
  unsafe_or_wrong_claim    an unanswerable question was answered, or (after the two checks below) the shown answer has a
                           claim the judge calls wrong or dangerous
  verifier_false_refusal   the draft (verifier off) was correct but the verifier's answer is not
  retrieval_miss           some labelled page group (relevant or acceptable pages) is missing from the context
  generation_error         the evidence was in the context but the answer is wrong, incomplete, or the model refused itself
Order of the checks: verifier_false_refusal, retrieval_miss, unsafe_or_wrong_claim, generation_error (unanswerable: always
unsafe_or_wrong_claim).
"""
import argparse
import copy
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from eval.judge import PROMPT_VERSION, answer_text, grade
from eval.run import holds
from eval.stats import pct, with_ci, wilson
from src.access import Principal
from src.answer import Draft, answer_cfg, finalize, generate, needs_retry, retry
from src.context import build_context
from src.llm import LLMClient, QuotaExhausted, load_config

TYPES = ["error_message", "symptom", "version", "cross_product", "unanswerable"]
CATEGORIES = ["retrieval_miss", "generation_error", "verifier_false_refusal", "unsafe_or_wrong_claim"]


def pages_covered(q: dict, context_pages: set) -> bool:
    """Every labelled page group (relevant pages in the group, or any acceptable page) has a page in the context."""
    ok = set(q.get("acceptable_pages", []))
    return all(any(p in context_pages for p in set(group) | ok) for group in q["relevant"])


def classify(q: dict, pages_ok: bool, off: dict, on: dict) -> str:
    """off / on: {"refused": bool, "judge": judge.grade() result}. Returns "correct" or one of CATEGORIES."""
    if on["judge"]["correct"]:
        return "correct"
    if q["expected"] == "refuse":
        return "unsafe_or_wrong_claim"
    if off["judge"]["correct"]:
        return "verifier_false_refusal"
    if not pages_ok:
        return "retrieval_miss"
    if not on["refused"] and on["judge"]["wrong_or_dangerous_claims"]:
        return "unsafe_or_wrong_claim"
    return "generation_error"


def load_questions(cfg: dict, split: str, dev: bool) -> list:
    qs = [json.loads(line) for line in Path(cfg["paths"]["eval_dir"], "questions.jsonl").open(encoding="utf8")]
    qs = [q for q in qs if q["split"] == split and (q.get("dev") or not dev)]
    if bad := [q["id"] for q in qs if not q["verified"] or (q["expected"] == "answer" and not q.get("key_points"))]:
        raise SystemExit(f"questions without a verified flag or key_points, review them first: {bad}")
    return qs


def run_question(q, who, cfg, llm, salt):
    from src.search import search
    t0, i0 = time.perf_counter(), len(llm.events)
    hits = search(q["question"], k=cfg["retrieval"]["k_context"], principal=who, cfg=cfg)
    items = build_context(hits, who, cfg)
    draft, refused, provider = (generate(q["question"], items, cfg, llm, cache="answer", salt=salt, stop_on_quota=True) if items
                                else (Draft("not_found", "none", "", "", []), True, ""))
    retried = False
    if items and needs_retry(draft, cfg):  # stage 16; the first pass above stays cached, so only the second pass costs tokens
        items, hits, draft, refused, provider, retried = retry(q["question"], items, hits, draft, refused, provider, who, None, cfg, llm,
                                                              cache="answer", salt=salt, stop_on_quota=True)
    ctx_pages = {it["source_path"] for it in items}
    row = {"id": q["id"], "retried": retried, "type": q["type"], "answerable": q["expected"] == "answer", "provider": provider or "none",
           "context_pages": sorted(ctx_pages), "pages_ok": pages_covered(q, ctx_pages) if q["relevant"] else None,
           "evidence_in_context": (sum(any(holds(it["source_path"], it["text"], e) for it in items) for e in q["evidence"])
                                   / len(q["evidence"])) if q["evidence"] else None,
           "drafted_steps": len(draft.steps), "kind": draft.kind, "coverage": draft.coverage, "missing": draft.missing}
    for mode, verify in (("off", False), ("on", True)):
        ans = finalize(q["question"], items, copy.deepcopy(draft), refused, provider, who, cfg, verify, llm, stop_on_quota=True)
        text = None if ans.refused else answer_text(ans.summary, ans.steps)
        row[mode] = {"refused": ans.refused, "blocked": ans.blocked, "steps_shown": len(ans.steps), "answer": text,
                     "judge": grade(q, text, llm, cfg)}
        if verify:
            row[mode].update(verified_by=ans.verified_by, partial=bool(ans.partial),
                             claims=[{"text": s.text, "claim": s.claim, "why": s.claim_why} for s in ans.checked])
    row["category"] = classify(q, row["pages_ok"] is not False, row["off"], row["on"])
    row["tokens"] = llm.usage_by_model(i0)
    row["seconds"] = round(time.perf_counter() - t0, 1)
    return row


def summarize(rows: list) -> dict:
    n = len(rows)
    ans, una = [r for r in rows if r["answerable"]], [r for r in rows if not r["answerable"]]
    out = {"n": n, "answerable": len(ans), "unanswerable": len(una)}
    for mode in ("on", "off"):
        ok = sum(r[mode]["judge"]["correct"] for r in rows)
        out[mode] = {"correct": ok, "accuracy": ok / n if n else 0, "ci95": wilson(ok, n),
                     "answerable_correct": sum(r[mode]["judge"]["correct"] for r in ans),
                     "answerable_partially_correct": sum(r[mode]["judge"]["verdict"] == "partially_correct" for r in ans),
                     "answerable_incorrect": sum(r[mode]["judge"]["verdict"] == "incorrect" for r in ans),
                     "answerable_refused": sum(r[mode]["refused"] for r in ans),
                     "unanswerable_refused": sum(r[mode]["refused"] for r in una)}
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    out["by_type"] = {t: {"n": len(rs), "correct": sum(r["on"]["judge"]["correct"] for r in rs),
                          "correct_verifier_off": sum(r["off"]["judge"]["correct"] for r in rs)} for t, rs in by_type.items()}
    # the writer's own coverage flag (new answer format only): does "full" go with a right draft, "partial" / "none" with a wrong one?
    out["coverage"] = {c: {"n": sum(r.get("coverage") == c for r in rows),
                           "draft_correct": sum(r.get("coverage") == c and r["off"]["judge"]["correct"] for r in rows)}
                       for c in ("full", "partial", "none")}
    ret = [r for r in rows if r.get("retried")]  # old result files have no such key
    out["retried"] = {"n": len(ret), "correct": sum(r["on"]["judge"]["correct"] for r in ret), "answerable": sum(r["answerable"] for r in ret),
                      "unanswerable": sum(not r["answerable"] for r in ret),
                      "unanswerable_refused": sum(not r["answerable"] and r["on"]["refused"] for r in ret)}
    out["failures"] = dict(Counter(r["category"] for r in rows if r["category"] != "correct"))
    out["generation_error_model_refused"] = sum(r["category"] == "generation_error" and r["off"]["refused"] for r in rows)
    out["wrong_claim_shown"] = sum(bool(r["on"]["judge"]["wrong_or_dangerous_claims"]) and not r["on"]["refused"] for r in rows)
    out["evidence_in_context_all"] = sum(r["evidence_in_context"] == 1 for r in ans)
    return out


def tokens_total(rows: list) -> dict:
    """Tokens behind these results per model (cost to produce, cached or not) and what this invocation spent."""
    total = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for m, u in r["tokens"].items():
            for k, v in u.items():
                total[m][k] += v
    return {m: dict(u) for m, u in total.items()}


def markdown(s: dict, meta: dict, tok: dict) -> str:
    a = s["answerable"]
    lines = [f"**Accuracy: {with_ci(s['on']['correct'], s['n'])}** on {meta['split']}"
             f"{' (dev subset)' if meta['dev'] else ''} ({s['n']} questions: {a} answerable, {s['unanswerable']} unanswerable).",
             "", "| | Verifier on (pipeline as configured) | Verifier off (draft) |", "|---|--:|--:|"]
    lines.append(f"| Accuracy (correct + correctly refused) / all | {pct(s['on']['accuracy'])} | {pct(s['off']['accuracy'])} |")
    for label, key, den in (("Answerable answered correctly", "answerable_correct", a),
                            ("Answerable partially correct (not counted as correct)", "answerable_partially_correct", a),
                            ("Answerable incorrect", "answerable_incorrect", a),
                            ("Answerable refused (false refusals)", "answerable_refused", a),
                            ("Unanswerable refused (correct)", "unanswerable_refused", s["unanswerable"])):
        lines.append(f"| {label} | {s['on'][key]} of {den} | {s['off'][key]} of {den} |")
    lines += ["", "| Question type | n | Correct (verifier on) | Correct (verifier off) |", "|---|--:|--:|--:|"]
    lines += [f"| {t} | {s['by_type'][t]['n']} | {s['by_type'][t]['correct']} | {s['by_type'][t]['correct_verifier_off']} |"
              for t in TYPES if t in s["by_type"]]
    if any(v["n"] for v in s["coverage"].values()):
        lines += ["", "The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):", "",
                  "| Writer says | Questions | Draft correct |", "|---|--:|--:|"]
        lines += [f"| {c} | {v['n']} | {v['draft_correct']} |" for c, v in s["coverage"].items()]
    if s["retried"]["n"]:
        t = s["retried"]
        lines += ["", f"**Retry (stage 16)** ran for {t['n']} questions ({t['answerable']} answerable, {t['unanswerable']} unanswerable): "
                      f"{t['correct']} of them correct afterwards (unanswerable ones still refused: {t['unanswerable_refused']} of {t['unanswerable']})."]
    nf = sum(s["failures"].values())
    lines += ["", f"**Failure breakdown** ({nf} questions not correct, verifier on):", "", "| Category | Questions |", "|---|--:|"]
    lines += [f"| {c} | {s['failures'].get(c, 0)} |" for c in CATEGORIES]
    lines += ["", f"Of the {s['failures'].get('generation_error', 0)} generation errors, {s['generation_error_model_refused']} were the "
              f"model refusing by itself. Evidence fully inside the context for {s['evidence_in_context_all']} of {a} answerable questions. "
              f"Shown answers with a wrong or dangerous claim: {s['wrong_claim_shown']}.", "",
              "| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |", "|---|--:|--:|--:|--:|--:|--:|"]
    lines += [f"| {m} | {u['calls']} | {u['cached_calls']} | {u['prompt_tokens']} | {u['completion_tokens']} | {u['total_tokens']} | {u['fresh_total_tokens']} |"
              for m, u in sorted(tok.items())]
    lines += ["", f"Split: {meta['split']}. Role: {meta['role']}. Collection {meta['collection']} ({meta['embedding']}), k_context {meta['k_context']}, "
                  f"max_context_chars {meta['max_context_chars']}, max_section_chars {meta['max_section_chars']}. Answer LLM {meta['answer_llm']} "
                  f"(reasoning_effort {meta['reasoning_effort']}). Answer providers: {meta['providers']}. "
                  f"Verifier: {meta['verifier']}{' (' + meta['verifier_model'] + ')' if meta['verifier'] == 'llm' else ''}, used for: {meta['verified_by']}. Judge {meta['judge']} (prompt {PROMPT_VERSION}). "
                  f"Retry: {'on' if meta['retry'] else 'off'}. Answer salt: {meta['salt'] or '(none)'}.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="score the holdout split instead of tune")
    ap.add_argument("--dev", action="store_true", help="only the dev subset of the split")
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", default="admin", choices=["public", "member", "admin"])
    ap.add_argument("--licenses", default="")
    ap.add_argument("--collection", default=None)
    ap.add_argument("--embedding", default=None)
    ap.add_argument("--embedding-device", default=None)
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (smoke test)")
    ap.add_argument("--no-retry", action="store_true", help="switch the stage-16 retry off (A/B against a run with it on)")
    ap.add_argument("--wait", action="store_true", help="when a Groq daily quota is used up, sleep and retry instead of stopping (checks every 10 minutes)")
    ap.add_argument("--salt", default="", help="changes the answer cache key, to repeat a run for real (measures run-to-run spread)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = load_config()
    cfg = answer_cfg(cfg)  # context sizes of the configured answer LLM
    if a.collection:
        cfg["qdrant"]["collection"] = a.collection
    if a.embedding:
        cfg["models"]["embedding"] = a.embedding
    if a.embedding_device:
        cfg["models"]["embedding_device"] = a.embedding_device
    if a.no_retry:
        cfg["retry"] = {**cfg["retry"], "enabled": False}
    who = Principal(a.role, frozenset(x for x in a.licenses.split(",") if x))
    split = "holdout" if a.final else "tune"
    qs = load_questions(cfg, split, a.dev)
    if a.limit:
        qs = qs[:a.limit]
    llm = LLMClient(cfg["llm"], say=lambda m: print(m, flush=True))

    rows = []
    try:
        for i, q in enumerate(qs, 1):
            while True:
                try:
                    r = run_question(q, who, cfg, llm, a.salt)
                    break
                except QuotaExhausted as e:
                    if not a.wait:
                        raise
                    print(f"quota used up ({str(e)[:120]}); waiting 10 minutes, then retrying {q['id']}", flush=True)
                    time.sleep(600)
            rows.append(r)
            print(f"[{i}/{len(qs)}] {q['id']:8} {q['expected']:7} draft={r['off']['judge']['verdict']:17} shown={r['on']['judge']['verdict']:17} "
                  f"-> {r['category']} ({r['provider']}, {r['seconds']}s)", flush=True)
    except QuotaExhausted as e:
        print(f"\nSTOPPED after {len(rows)} of {len(qs)} questions: {e}\nEverything finished is cached; run the same command later to resume.")
        raise SystemExit(3)

    summary = summarize(rows)
    tok = tokens_total(rows)
    meta = {"split": split, "dev": a.dev, "role": a.role + (f"[{a.licenses}]" if a.licenses else ""), "collection": cfg["qdrant"]["collection"],
            "embedding": cfg["models"]["embedding"], "k_context": cfg["retrieval"]["k_context"], "max_context_chars": cfg["context"]["max_context_chars"],
            "max_section_chars": cfg["context"]["max_section_chars"], "answer_llm": cfg["answer"]["llm"], "reasoning_effort": cfg["answer"]["reasoning_effort"],
            "providers": dict(Counter(r["provider"] for r in rows)), "judge": cfg["eval"]["judge"]["model"], "salt": a.salt,
            "retry": cfg["retry"]["enabled"], "verifier": cfg["verify"]["method"], "verifier_model": cfg["verify"]["llm"]["model"],
            "verified_by": dict(Counter(r["on"]["verified_by"] for r in rows)), "prefer": cfg["llm"]["prefer"], "prefer_answer": cfg["answer"]["llm"], "tokens_spent_in_this_run": llm.usage_by_model()}
    out = Path(cfg["paths"]["eval_results"])
    out.mkdir(parents=True, exist_ok=True)
    stem = f"accuracy_{a.name}_{split}"
    (out / f"{stem}.json").write_text(json.dumps({"meta": meta, "summary": summary, "tokens": tok, "per_question": rows}, indent=2,
                                                 ensure_ascii=False, default=list), encoding="utf8")
    md = markdown(summary, meta, tok)
    (out / f"{stem}.md").write_text(md, encoding="utf8")
    print("\n" + md)


if __name__ == "__main__":
    main()
