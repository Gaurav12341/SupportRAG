"""Checks on eval/questions.jsonl: shape, counts, key points, verification fields, and that every cited page and quote
really is in the corpus."""
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "questions.jsonl"
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"

TYPE_COUNTS = {"error_message": 24, "symptom": 24, "version": 20, "cross_product": 16, "unanswerable": 20}
# The original 10 holdout questions were not touched in Phase 1 (docs/IMPROVEMENT_PLAN.md): their key points and assistant
# check are added right before the final holdout run (Phase 5). The list is explicit, so nothing else can lack them.
OLD_HOLDOUT = {"err-02", "err-06", "err-10", "sym-04", "sym-09", "ver-03", "ver-05", "x-03", "none-01", "none-06"}
norm = lambda s: " ".join(s.split())


@pytest.fixture(scope="module")
def questions():
    return [json.loads(line) for line in QUESTIONS.read_text(encoding="utf8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def corpus():
    if not CHUNKS.exists():
        pytest.skip("data/processed/chunks.jsonl not built (run python -m src.ingest)")
    pages = {}
    for line in CHUNKS.open(encoding="utf8"):
        r = json.loads(line)
        pages.setdefault(f"{r['source']}/{r['source_path'].split('/', 1)[1]}", []).append(norm(r["text"]))
    return pages


def test_counts_and_split(questions):
    assert len(questions) == 104
    assert dict(Counter(q["type"] for q in questions)) == TYPE_COUNTS
    assert dict(Counter(q["split"] for q in questions)) == {"tune": 70, "holdout": 34}
    assert len({q["id"] for q in questions}) == 104


def test_every_type_appears_in_holdout(questions):
    assert {q["type"] for q in questions if q["split"] == "holdout"} == set(TYPE_COUNTS)


def test_shape(questions):
    for q in questions:
        assert isinstance(q["verified"], bool)
        assert q["question"].strip() and q["products"]
        if q["type"] == "unanswerable":
            assert q["expected"] == "refuse" and q["relevant"] == [] and q["absent_terms"]
        else:
            assert q["expected"] == "answer" and q["evidence"]
            assert all(group for group in q["relevant"]) and q["relevant"]
    for q in questions:
        if q["type"] == "cross_product":
            assert len(q["products"]) >= 2 and len(q["relevant"]) >= 2


def test_everything_is_verified_by_the_assistant_except_the_untouched_old_holdout(questions):
    """Decision D4: the assistant verified the questions and key points (and says so in verify_note)."""
    for q in questions:
        assert q["verified"] is True
        if q["id"] in OLD_HOLDOUT:
            assert "verified_by" not in q and "key_points" not in q  # untouched until Phase 5
        else:
            assert q["verified_by"] == "assistant" and len(q["verify_note"]) > 20, q["id"]


def test_key_points(questions):
    """Every answerable question except the untouched old holdout ones has 1-4 short key points, at least one essential."""
    for q in questions:
        if q["expected"] != "answer":
            assert "key_points" not in q
            continue
        if q["id"] in OLD_HOLDOUT:
            assert "key_points" not in q
            continue
        kps = q["key_points"]
        assert 1 <= len(kps) <= 4, q["id"]
        assert all(isinstance(k["text"], str) and len(k["text"]) > 10 and isinstance(k["essential"], bool) for k in kps), q["id"]
        assert any(k["essential"] for k in kps), q["id"]
        assert isinstance(q["acceptable_pages"], list)
        if q["type"] == "cross_product":  # one essential point per product
            assert sum(k["essential"] for k in kps) >= 2, q["id"]


def test_old_holdout_questions_are_unchanged(questions):
    """Phase 1 must not touch the holdout split except to add new questions to it."""
    old = {q["id"]: q for q in questions if q["id"] in OLD_HOLDOUT}
    assert len(old) == 10
    for q in old.values():
        assert q["split"] == "holdout" and not q.get("dev") and "draft_id" not in q


def test_dev_subset(questions):
    dev = [q for q in questions if q.get("dev")]
    assert len(dev) == 40 and all(q["split"] == "tune" for q in dev)
    assert set(Counter(q["type"] for q in dev)) == set(TYPE_COUNTS)  # every type is represented


def test_relevant_pages_and_quotes_exist_in_corpus(questions, corpus):
    for q in questions:
        for group in q["relevant"]:
            for page in group:
                assert page in corpus, f"{q['id']}: {page} not in corpus"
        for page in q.get("acceptable_pages", []):
            assert page in corpus, f"{q['id']}: acceptable page {page} not in corpus"
        for ev in q["evidence"]:
            texts = corpus[ev["page"]]
            quote = norm(ev["quote"])
            assert any(quote in t for t in texts) or quote in " ".join(texts), f"{q['id']}: quote missing in {ev['page']}"


def test_unanswerable_terms_absent_from_whole_corpus(questions, corpus):
    everything = " ".join(t for texts in corpus.values() for t in texts).lower()
    for q in questions:
        for term in q["absent_terms"]:
            assert term.lower() not in everything, f"{q['id']}: {term!r} is in the corpus"
        if q["type"] == "unanswerable":  # the question must really name the tool it is about
            assert any(term.lower() in q["question"].lower() for term in q["absent_terms"]), q["id"]
