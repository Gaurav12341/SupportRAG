"""Metric maths for eval/run.py, checked by hand-computed cases (no Qdrant needed)."""
import pytest

from eval.run import page_of, recall_at_k, reciprocal_rank, summarize

PAGES = ["a", "b", "c", "d", "e", "f"]


def test_recall_single_group_with_alternates():
    assert recall_at_k(PAGES, [["z", "c"]], 5) == 1.0
    assert recall_at_k(PAGES, [["f"]], 5) == 0.0
    assert recall_at_k(PAGES, [["f"]], 10) == 1.0


def test_recall_cross_product_needs_each_group():
    assert recall_at_k(PAGES, [["a"], ["z"]], 5) == 0.5
    assert recall_at_k(PAGES, [["a"], ["e"]], 5) == 1.0


def test_reciprocal_rank():
    assert reciprocal_rank(PAGES, [["c"]]) == pytest.approx(1 / 3)
    assert reciprocal_rank(PAGES, [["z"], ["b", "d"]]) == pytest.approx(1 / 2)
    assert reciprocal_rank(PAGES, [["z"]]) == 0.0


def test_summarize_overall_and_per_type():
    rows = [{"type": "t1", "recall@5": 1.0, "recall@10": 1.0, "mrr": 1.0},
            {"type": "t2", "recall@5": 0.0, "recall@10": 1.0, "mrr": 0.5}]
    s = summarize(rows)
    assert s["overall"] == {"n": 2, "recall@5": 0.5, "recall@10": 1.0, "mrr": 0.75}
    assert s["t2"]["recall@5"] == 0.0 and s["t1"]["n"] == 1


def test_page_of_matches_questions_file_format():
    assert page_of({"source": "postgres", "source_path": "postgres/mvcc.html"}) == "postgres/mvcc.html"
    assert page_of({"source": "stackoverflow", "source_path": "stackoverflow/123"}) == "stackoverflow/123"
