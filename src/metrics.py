"""The evaluation numbers for the UI, read from eval/results/*.json. Nothing is typed in here or computed beyond counting and dividing what the files hold,
so the screen can never disagree with the README tables (which are copied from the same files)."""
import json
from pathlib import Path

from src.access import ROOT

HOLDOUT = "accuracy_final_holdout"
CURRENT = "accuracy_p3_dev_tune"  # the setup the pipeline runs today (the holdout run above was made with it)
PROGRESS = [  # (file, what was different), in the order the work happened
    ("accuracy_baseline_tune", "Local Qwen2.5-3B writer, NLI verifier"),
    ("accuracy_baseline_run2_tune", "Same again (run-to-run spread)"),
    ("accuracy_p2_dev_tune", "Groq gpt-oss-120b writer, wider context, NLI verifier"),
    ("accuracy_p3_dev_tune", "LLM claim check instead of the NLI verifier"),
    ("accuracy_p4b_dev_tune", "Plus the retry loop (measured, left off)"),
]
RETRIEVAL = [
    ("baseline_dense_tune", "Dense only"),
    ("step_hybrid_tune", "Dense + BM25, merged with RRF"),
    ("step_rerank_tune", "Hybrid + cross-encoder rerank"),
]


def _load(results, name):
    path = results / f"{name}.json"
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else None


def _safety(d):
    attacks, normal = d["attacks"], d["normal"]
    return {"attacks": len(attacks), "attacks_blocked": sum(a["verdict"]["blocked"] for a in attacks),
            "normal": len(normal), "normal_blocked": sum(n["verdict"]["blocked"] for n in normal),
            "poisoned": len(d["poisoned_chunks"]), "poisoned_caught": sum(bool(p.get("rule")) for p in d["poisoned_chunks"]),
            "real_chunks": d["real_chunks"], "real_chunks_flagged": len(d["real_chunks_flagged"])}


def evaluation(cfg):
    results = ROOT / cfg["paths"]["eval_results"]
    out = {"holdout": None, "progress": [], "retrieval": [], "safety": None, "safety_first_run": None}
    if d := _load(results, HOLDOUT):
        s, m = d["summary"], d["meta"]
        on = s["on"]
        out["holdout"] = {
            "n": s["n"], "answerable": s["answerable"], "unanswerable": s["unanswerable"],
            "accuracy": on["accuracy"], "ci95": on["ci95"], "correct": on["correct"],
            "outcomes": {"correct": on["answerable_correct"], "partial": on["answerable_partially_correct"], "incorrect": on["answerable_incorrect"],
                         "false_refusal": on["answerable_refused"], "correctly_refused": on["unanswerable_refused"]},
            "by_type": [{"type": k, **v} for k, v in s["by_type"].items()],
            "failures": s["failures"], "evidence_in_context": s["evidence_in_context_all"], "wrong_claim_shown": s["wrong_claim_shown"],
            "setup": {"split": m["split"], "writer": m["answer_llm"], "judge": m["judge"], "verifier": m["verifier_model"], "k_context": m["k_context"],
                      "embedding": m["embedding"], "collection": m["collection"], "retry": m["retry"]},
            "tokens": {k: {"calls": v["calls"], "total": v["total_tokens"]} for k, v in d["tokens"].items()},
        }
    for name, label in PROGRESS:
        if d := _load(results, name):
            s = d["summary"]
            out["progress"].append({"file": name, "current": name == CURRENT, "label": label, "split": d["meta"]["split"], "n": s["n"], "accuracy": s["on"]["accuracy"], "ci95": s["on"]["ci95"],
                                    "draft_accuracy": s["off"]["accuracy"]})
    for name, label in RETRIEVAL:
        if d := _load(results, name):
            o = d["summary"]["overall"]
            out["retrieval"].append({"file": name, "label": label, "n": o["n"], "recall5": o["recall@5"], "recall10": o["recall@10"], "mrr": o["mrr"],
                                     "median_ms": d.get("median_search_ms")})
    if d := _load(results, "input_safety"):
        out["safety"] = _safety(d)
    if d := _load(results, "input_safety_first_run"):
        out["safety_first_run"] = _safety(d)
    return out
