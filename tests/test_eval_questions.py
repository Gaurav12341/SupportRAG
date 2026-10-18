"""Checks on eval/questions.jsonl: shape, counts, and that every cited page and quote really is in the corpus."""
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "questions.jsonl"
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"

TYPE_COUNTS = {"error_message": 10, "symptom": 10, "version": 8, "cross_product": 6, "unanswerable": 6}
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
    assert len(questions) == 40
    assert dict(Counter(q["type"] for q in questions)) == TYPE_COUNTS
    assert dict(Counter(q["split"] for q in questions)) == {"tune": 30, "holdout": 10}
    assert len({q["id"] for q in questions}) == 40


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


def test_relevant_pages_and_quotes_exist_in_corpus(questions, corpus):
    for q in questions:
        for group in q["relevant"]:
            for page in group:
                assert page in corpus, f"{q['id']}: {page} not in corpus"
        for ev in q["evidence"]:
            texts = corpus[ev["page"]]
            quote = norm(ev["quote"])
            assert any(quote in t for t in texts) or quote in " ".join(texts), f"{q['id']}: quote missing in {ev['page']}"


def test_unanswerable_terms_absent_from_whole_corpus(questions, corpus):
    everything = " ".join(t for texts in corpus.values() for t in texts).lower()
    for q in questions:
        for term in q["absent_terms"]:
            assert term.lower() not in everything, f"{q['id']}: {term!r} is in the corpus"
