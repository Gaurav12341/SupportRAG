"""The accuracy eval: Wilson interval, judge parsing and rules, failure classification, summary, draft helpers. No network."""
import json
from types import SimpleNamespace

import pytest

from eval import judge
from eval.accuracy import CATEGORIES, classify, pages_covered, summarize
from eval.drafts import assign_dev, find_quote, section_around
from eval.stats import wilson, with_ci
from src.llm import Reply, load_config

CFG = load_config()


# ---------- stats ----------

def test_wilson_known_values():
    lo, hi = wilson(18, 30)
    assert lo == pytest.approx(0.4231, abs=1e-3) and hi == pytest.approx(0.7541, abs=1e-3)
    assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == 1.0
    assert wilson(0, 0) == (0.0, 0.0)


def test_with_ci_text():
    assert with_ci(15, 30).startswith("15/30 = 50.0% (95% CI 33.2-66.8%)")


# ---------- judge ----------

Q = {"id": "q", "question": "How?", "expected": "answer", "evidence": [{"quote": "do the thing"}],
     "key_points": [{"text": "do the thing", "essential": True}, {"text": "extra", "essential": False}]}
QU = {"id": "u", "question": "Tool?", "expected": "refuse", "evidence": [], "key_points": []}


def verdict(v, missing=(), wrong=(), reason="r", stated=None):
    out = {"verdict": v, "missing_points": list(missing), "wrong_or_dangerous_claims": list(wrong), "reason": reason}
    if stated is not None:
        out["points_stated"] = stated
    return json.dumps(out)


def test_parse_verdict_accepts_valid_and_rejects_junk():
    assert judge.parse_verdict(verdict("correct"))["verdict"] == "correct"
    assert judge.parse_verdict("not json") is None
    assert judge.parse_verdict(json.dumps({"verdict": "maybe", "missing_points": [], "wrong_or_dangerous_claims": [], "reason": ""})) is None
    assert judge.parse_verdict(json.dumps({"verdict": "correct"})) is None


def test_verdict_is_derived_from_the_point_flags_when_present():
    # Q has one essential and one optional point: [essential, optional]
    judge_said = lambda v, stated, wrong=(): judge.parse_verdict(verdict(v, stated=stated, wrong=wrong), Q)
    assert judge_said("partially_correct", [True, False])["verdict"] == "correct"            # optional point missing is fine
    assert judge_said("partially_correct", [True, False])["corrected"] is True
    assert judge_said("correct", [False, True])["verdict"] == "incorrect"                    # no essential point stated
    assert judge_said("correct", [True, True], wrong=["rm -rf /"])["verdict"] == "incorrect"  # a wrong claim always decides
    two = {**Q, "key_points": [{"text": "a" * 12, "essential": True}, {"text": "b" * 12, "essential": True}]}
    assert judge.parse_verdict(verdict("correct", stated=[True, False]), two)["verdict"] == "partially_correct"
    assert judge.parse_verdict(verdict("correct", stated=[True, True]), two)["verdict"] == "correct"
    # flags of the wrong length are ignored and the judge's own verdict is kept
    assert judge.parse_verdict(verdict("incorrect", stated=[True]), Q)["verdict"] == "incorrect"


def test_contradictory_verdicts_are_corrected():
    assert judge.parse_verdict(verdict("correct", wrong=["rm -rf /"]))["verdict"] == "incorrect"
    assert judge.parse_verdict(verdict("correct", missing=["restart"]))["verdict"] == "partially_correct"
    assert judge.parse_verdict(verdict("correct", missing=["restart"]))["corrected"] is True
    assert judge.parse_verdict(verdict("partially_correct", missing=["x"]))["corrected"] is False


class FakeLLM:
    def __init__(self, text):
        self.text, self.calls = text, []

    def chat_full(self, messages, **kw):
        self.calls.append((messages, kw))
        return Reply(self.text, "groq", "judge-model", {"total_tokens": 10})


def test_rules_need_no_llm_call():
    llm = FakeLLM("unused")
    assert judge.grade(Q, None, llm, CFG) | {} == {"verdict": "refused", "correct": False, "missing_points": [], "wrong_or_dangerous_claims": [],
                                                 "reason": "refused", "judged_by": "rule"}
    assert judge.grade(QU, None, llm, CFG)["correct"] is True
    assert judge.grade(QU, "1. made up", llm, CFG)["verdict"] == "incorrect"
    assert llm.calls == []


def test_grade_calls_the_judge_with_no_fallback_and_the_key_points_in_the_prompt():
    llm = FakeLLM(verdict("correct", stated=[True, False]))
    got = judge.grade(Q, "1. do the thing", llm, CFG)
    assert got["correct"] is True and got["judged_by"] == "judge-model"
    messages, kw = llm.calls[0]
    assert kw["fallback"] is False and kw["prefer"] == "groq" and kw["model"] == CFG["eval"]["judge"]["model"] and kw["temperature"] == 0
    assert "1. [ESSENTIAL] do the thing" in messages[1]["content"] and "2. [optional] extra" in messages[1]["content"]
    assert "1. do the thing" in messages[1]["content"]


def test_answer_text_has_steps_and_warnings_but_no_citations():
    steps = [SimpleNamespace(text="run `x`", warnings=["careful"], cited=["c1"])]
    assert judge.answer_text("", steps) == "1. run `x`\n   WARNING: careful"
    assert judge.answer_text("The cause is y.", steps).startswith("The cause is y.\n1. run `x`")


# ---------- classification ----------

def res(correct, verdict="incorrect", wrong=(), refused=False):
    return {"refused": refused, "judge": {"correct": correct, "verdict": verdict, "wrong_or_dangerous_claims": list(wrong)}}


A = {"expected": "answer"}
U = {"expected": "refuse"}


def test_classify_each_category():
    assert classify(A, True, res(True), res(True, "correct")) == "correct"
    assert classify(U, True, res(False), res(True, "correct", refused=True)) == "correct"
    assert classify(U, True, res(False), res(False)) == "unsafe_or_wrong_claim"
    assert classify(A, True, res(True, "correct"), res(False, "refused", refused=True)) == "verifier_false_refusal"
    assert classify(A, False, res(False), res(False, "refused", refused=True)) == "retrieval_miss"
    assert classify(A, True, res(False), res(False, wrong=["bad"])) == "unsafe_or_wrong_claim"
    assert classify(A, True, res(False), res(False, "refused", refused=True)) == "generation_error"
    assert classify(A, True, res(False, "partially_correct"), res(False, "partially_correct")) == "generation_error"
    assert {"retrieval_miss", "generation_error", "verifier_false_refusal", "unsafe_or_wrong_claim"} == set(CATEGORIES)


def test_retrieval_miss_beats_a_wrong_claim_but_verifier_beats_both():
    assert classify(A, False, res(False), res(False, wrong=["bad"])) == "retrieval_miss"
    assert classify(A, False, res(True, "correct"), res(False, "refused", refused=True)) == "verifier_false_refusal"


def test_pages_covered_needs_every_group_and_accepts_acceptable_pages():
    q = {"relevant": [["a", "a2"], ["b"]], "acceptable_pages": ["c"]}
    assert not pages_covered(q, {"a"})
    assert pages_covered(q, {"a2", "b"})
    assert pages_covered(q, {"c"})  # an acceptable page satisfies any group
    assert not pages_covered({"relevant": [["a"]]}, {"x"})


def test_summarize_counts():
    def row(i, typ, answerable, on, off, cat, refused_on=False, refused_off=False):
        return {"id": i, "type": typ, "answerable": answerable, "category": cat, "evidence_in_context": 1.0 if answerable else None,
                "on": res(on, "correct" if on else "incorrect", refused=refused_on), "off": res(off, "correct" if off else "incorrect", refused=refused_off)}
    rows = [row("a", "symptom", True, True, True, "correct"),
            row("b", "symptom", True, False, True, "verifier_false_refusal", refused_on=True),
            row("c", "unanswerable", False, True, True, "correct", refused_on=True, refused_off=True),
            row("d", "unanswerable", False, False, False, "unsafe_or_wrong_claim")]
    s = summarize(rows)
    assert s["n"] == 4 and s["on"]["correct"] == 2 and s["off"]["correct"] == 3
    assert s["on"]["answerable_refused"] == 1 and s["on"]["unanswerable_refused"] == 1
    assert s["failures"] == {"verifier_false_refusal": 1, "unsafe_or_wrong_claim": 1}
    assert s["by_type"]["symptom"] == {"n": 2, "correct": 1, "correct_verifier_off": 2}


# ---------- draft helpers ----------

PAGE = "# Title\n\nIntro.\n\n## Fix it\n\nRun   this\ncommand now.\n\nMore.\n\n## Other\n\nUnrelated.\n"


def test_find_quote_ignores_whitespace_differences():
    start, end = find_quote(PAGE, "Run this command now.")
    assert PAGE[start:end].startswith("Run") and find_quote(PAGE, "not here") is None


def test_section_around_returns_the_section_and_windows_long_ones():
    span = find_quote(PAGE, "command now.")
    sec = section_around(PAGE, span)
    assert sec.startswith("## Fix it") and "More." in sec and "Unrelated" not in sec
    long_page = "## S\n\n" + "x " * 3000 + "NEEDLE here " + "y " * 3000
    window = section_around(long_page, find_quote(long_page, "NEEDLE here"), 600)
    assert "NEEDLE" in window and len(window) <= 600


def test_assign_dev_is_proportional_and_stable():
    qs = [{"id": f"{t}{i}", "type": t, "split": "tune"} for t, n in (("a", 30), ("b", 20), ("c", 10)) for i in range(n)]
    qs += [{"id": "h", "type": "a", "split": "holdout"}]
    assign_dev(qs, n=30)
    dev = [q for q in qs if q.get("dev")]
    assert len(dev) == 30 and all(q["split"] == "tune" for q in dev)
    assert {t: sum(q["type"] == t for q in dev) for t in "abc"} == {"a": 15, "b": 10, "c": 5}
    before = {q["id"] for q in dev}
    assign_dev(qs, n=30)  # does not move
    assert {q["id"] for q in qs if q.get("dev")} == before


# ---------- run-to-run spread ----------

def test_spread_compare():
    from eval.spread import compare
    row = lambda i, ok: {"id": i, "on": {"judge": {"correct": ok}}}  # noqa: E731
    a = [row("a", True), row("b", True), row("c", False), row("d", False)]
    b = [row("a", True), row("b", False), row("c", True), row("d", False)]
    assert compare(a, b) == {"n": 4, "correct_a": 2, "correct_b": 2, "same_outcome": 2, "both_correct": 1, "only_a": 1, "only_b": 1}
