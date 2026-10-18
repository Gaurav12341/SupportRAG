"""Tests for stages 5-6 and basic search. Use Qdrant's in-memory mode, so Docker is not needed."""
import pytest
from qdrant_client import QdrantClient

import src.index as index
import src.search as search_mod
from src.llm import load_config
from src.store import EmbeddingModelMismatch, point_id

CHUNKS = [
    {"chunk_id": "k8s/a.md#0", "product": "kubernetes", "title": "Debug pods", "url": "u1", "doc_type": "troubleshooting",
     "access_level": "public", "text": "A pod in CrashLoopBackOff keeps restarting. Check kubectl logs --previous."},
    {"chunk_id": "pg/b.html#0", "product": "postgres", "title": "VACUUM", "url": "u2", "doc_type": "reference",
     "access_level": "public", "text": "VACUUM reclaims storage occupied by dead tuples in a table."},
    {"chunk_id": "kafka/c.md#0", "product": "kafka", "title": "Consumer groups", "url": "u3", "doc_type": "concept",
     "access_level": "public", "text": "A consumer group rebalance happens when members join or leave the group."},
]


@pytest.fixture
def env(monkeypatch):
    cfg = load_config()
    cfg["qdrant"]["collection"] = "test_docs"
    qc = QdrantClient(":memory:")
    monkeypatch.setattr(index, "client", lambda cfg: qc)
    monkeypatch.setattr(index, "read_chunks", lambda cfg: list(CHUNKS))
    monkeypatch.setattr(index, "load_config", lambda: cfg)
    monkeypatch.setattr(search_mod, "load_config", lambda: cfg)
    return cfg, qc


def test_point_id_is_stable():
    assert point_id("a#0") == point_id("a#0") != point_id("a#1")


def test_rerun_does_not_duplicate_or_reembed(env):
    cfg, qc = env
    first = index.run()
    second = index.run()
    assert first["embedded_now"] == 3 and first["points_in_collection"] == 3
    assert second["embedded_now"] == 0 and second["points_in_collection"] == 3


def test_changed_chunk_is_replaced_not_added(env, monkeypatch):
    cfg, qc = env
    index.run()
    changed = [dict(CHUNKS[0], text="Totally different text about pods.")] + CHUNKS[1:]
    monkeypatch.setattr(index, "read_chunks", lambda cfg: changed)
    stats = index.run()
    assert stats["embedded_now"] == 1 and stats["points_in_collection"] == 3


def test_model_name_is_saved_in_collection(env):
    cfg, qc = env
    index.run()
    assert qc.get_collection("test_docs").config.metadata["embedding_model"] == cfg["models"]["embedding"]


def test_search_refuses_when_model_names_differ(env):
    cfg, qc = env
    index.run()
    other = {**cfg, "models": {**cfg["models"], "embedding": "BAAI/bge-base-en-v1.5"}}
    with pytest.raises(EmbeddingModelMismatch, match="bge-small-en-v1.5"):
        search_mod.search("anything", cfg=other, qc=qc)


def test_index_refuses_to_mix_models(env):
    cfg, qc = env
    index.run()
    cfg["models"]["embedding"] = "BAAI/bge-base-en-v1.5"
    with pytest.raises(EmbeddingModelMismatch):
        index.run()


def test_search_top_k_and_product_filter(env):
    cfg, qc = env
    index.run()
    hits = search_mod.search("pod keeps restarting", k=2, cfg=cfg, qc=qc)
    assert len(hits) == 2 and hits[0]["product"] == "kubernetes"
    only_pg = search_mod.search("pod keeps restarting", k=3, product="postgres", cfg=cfg, qc=qc)
    assert [h["product"] for h in only_pg] == ["postgres"]
