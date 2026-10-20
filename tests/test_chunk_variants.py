"""Recursive chunker, per-model query prefix, and the passage-level eval metric."""
import pytest

from eval.run import cover, holds, passage_scores
from src.embed import QUERY_PREFIX, query_prefix
from src.ingest.chunk import chunk_recursive, load_tokenizer
from src.llm import load_config

TOK = load_tokenizer(load_config()["models"]["embedding"])
DOC = ("# Title\n\nIntro sentence one. Intro sentence two.\n\n## Fix\n\n" + " ".join(f"Step {i} does something useful." for i in range(120))
       + "\n\n## Other\n\nShort section.\n\n```\n# not a heading\nrun --now\n```\n")


def test_every_chunk_is_an_exact_slice_and_fits():
    chunks = chunk_recursive(DOC, TOK, 100, 10)
    assert len(chunks) > 3
    assert all(c["text"] in DOC for c in chunks)
    assert all(c["n_tokens"] <= 100 for c in chunks)


def test_small_text_is_one_chunk():
    assert [c["text"] for c in chunk_recursive("Just one short paragraph.", TOK, 100, 10)] == ["Just one short paragraph."]


def test_prefers_to_cut_at_headings_over_mid_sentence():
    chunks = chunk_recursive(DOC, TOK, 100, 0)
    assert any(c["text"].startswith("## Other") for c in chunks)  # the heading starts a chunk, it is not cut off
    assert all(c["text"].rstrip().endswith((".", "```")) or c["text"] == chunks[-1]["text"] or c["text"].rstrip()[-1].isalnum() for c in chunks)


def test_overlap_repeats_text_but_never_exceeds_size():
    chunks = chunk_recursive(DOC, TOK, 100, 20)
    assert all(c["n_tokens"] <= 100 for c in chunks)
    assert any(b["text"][:25] in a["text"] for a, b in zip(chunks, chunks[1:]))  # a chunk starts with text the previous one ended with


def test_unsplittable_run_falls_back_to_token_windows():
    blob = "漢" * 400  # no separator at all, one token per character
    chunks = chunk_recursive(blob, TOK, 50, 0)
    assert len(chunks) > 1 and all(c["n_tokens"] <= 50 for c in chunks)


@pytest.mark.parametrize("name,prefix", [("BAAI/bge-small-en-v1.5", QUERY_PREFIX), ("BAAI/bge-base-en-v1.5", QUERY_PREFIX),
                                         ("BAAI/bge-m3", ""), ("sentence-transformers/all-MiniLM-L6-v2", "")])
def test_query_prefix_only_for_english_bge_v15(name, prefix):
    assert query_prefix(name) == prefix


def test_cover_and_holds():
    quote = "restart your PostgreSQL server now"
    assert cover(quote, "Please Restart your postgresql server now, then log in.") == 1.0
    assert cover(quote, "unrelated text about kafka") == 0.0
    assert cover(quote, "restart your PostgreSQL") < 1.0  # a quote cut by a chunk boundary is partly covered
    ev = {"page": "postgres/a.html", "quote": quote}
    assert holds("postgres/a.html", f"x {quote} y", ev)
    assert not holds("postgres/b.html", f"x {quote} y", ev)  # right words, wrong page


def test_passage_scores():
    q = {"evidence": [{"page": "p/a", "quote": "alpha beta gamma delta"}, {"page": "p/b", "quote": "one two three four"}]}
    hit = lambda src, path, text: {"source": src, "source_path": f"{src}/{path}", "text": text}
    hits = [hit("p", "z", "nothing here"), hit("p", "a", "so alpha beta gamma delta it is")]
    ctx = [{"source_path": "p/a", "text": "alpha beta gamma delta"}]
    s = passage_scores(q, hits, ctx)
    assert s["p_recall@5"] == 0.5 and s["p_mrr"] == 0.5 and s["ctx_recall"] == 0.5
