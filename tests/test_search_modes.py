"""BM25, RRF, rerank and the role/license-based access filter. In-memory Qdrant, so Docker is not needed
(except the last test, which is skipped when the real index is not running)."""
import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

import src.index as index
import src.search as S
from src.access import PRODUCTS, Principal
from src.llm import load_config

ROOT = Path(__file__).resolve().parent.parent


def chunk(cid, level, text, product="postgres"):
    return {"chunk_id": cid, "product": product, "title": cid, "url": "u", "doc_type": "howto",
            "access_level": level, "text": text}


CHUNKS = [
    chunk("pub/a#0", "public", "Dead tuples are removed by VACUUM so the table stops growing."),
    chunk("pub/b#0", "public", "A consumer group rebalance happens when members join or leave.", "kafka"),
    chunk("pub/c#0", "public", "Pods restart repeatedly with CrashLoopBackOff; read kubectl logs.", "kubernetes"),
    chunk("int/d#0", "internal", "Operators tune wal_level and archive_command for point in time backup."),
    chunk("int/e#0", "internal", "Monitoring the cluster: scrape kubelet metrics for node pressure.", "kubernetes"),
    chunk("res/f#0", "restricted", "Rotate the database password with ALTER ROLE and pg_hba.conf scram-sha-256."),
    chunk("res/g#0", "restricted", "Kafka SASL secrets live in the jaas config; never print the keystore password.", "kafka"),
]
MODES = S.MODES
PUBLIC, ADMIN = Principal.public(), Principal.admin()


@pytest.fixture
def env(monkeypatch):
    cfg = load_config()
    cfg["qdrant"]["collection"] = "test_search"
    qc = QdrantClient(":memory:")
    monkeypatch.setattr(index, "client", lambda cfg: qc)
    monkeypatch.setattr(index, "read_chunks", lambda cfg: list(CHUNKS))
    monkeypatch.setattr(index, "load_config", lambda: cfg)
    index.run()
    return cfg, qc


def levels(hits):
    return {h["access_level"] for h in hits}


def ids(hits):
    return {h["chunk_id"] for h in hits}


def test_rrf_rewards_chunks_found_by_both_lists():
    a = [{"chunk_id": "x"}, {"chunk_id": "y"}, {"chunk_id": "z"}]
    b = [{"chunk_id": "z"}, {"chunk_id": "x"}]
    merged = S.rrf([a, b], rrf_k=60)
    assert [h["chunk_id"] for h in merged] == ["x", "z", "y"]
    assert merged[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert merged[2]["score"] == pytest.approx(1 / 62)


def test_bm25_ranks_exact_token_first_and_skips_zero_scores():
    idx = S.BM25Index([chunk(f"c{i}", "public", t) for i, t in enumerate([
        "generic words about databases", "error code 53300 too many connections", "something else entirely"])])
    hits = idx.search("53300", 5, ADMIN, load_config())
    assert [h["chunk_id"] for h in hits] == ["c1"]


def test_hybrid_and_rerank_return_requested_k(env):
    cfg, qc = env
    for mode in ("hybrid", "rerank"):
        hits = S.search("pods restart CrashLoopBackOff", k=2, principal=ADMIN, mode=mode, cfg=cfg, qc=qc)
        assert len(hits) == 2 and hits[0]["chunk_id"] == "pub/c#0"


def test_rerank_default_k_is_k_context(env):
    cfg, qc = env
    cfg["retrieval"]["k_context"] = 3
    assert len(S.search("database", principal=ADMIN, mode="rerank", cfg=cfg, qc=qc)) == 3


@pytest.mark.parametrize("mode", MODES)
def test_public_never_gets_internal_or_restricted(env, mode):
    cfg, qc = env
    # the best possible match for each question is a restricted/internal chunk
    for c in CHUNKS:
        hits = S.search(c["text"], k=10, principal=PUBLIC, mode=mode, cfg=cfg, qc=qc)
        assert hits and levels(hits) == {"public"}, (mode, c["chunk_id"])


@pytest.mark.parametrize("mode", MODES)
def test_member_sees_non_public_only_for_licensed_products(env, mode):
    cfg, qc = env
    member = Principal.member("kubernetes")  # licensed for kubernetes, not postgres or kafka
    for c in CHUNKS:
        for h in S.search(c["text"], k=10, principal=member, mode=mode, cfg=cfg, qc=qc):
            assert h["access_level"] == "public" or h["product"] == "kubernetes", (mode, c["chunk_id"], h["chunk_id"])
    # and the licensed product's internal chunk does come back for its own text
    hits = S.search(CHUNKS[4]["text"], k=10, principal=member, mode=mode, cfg=cfg, qc=qc)
    assert "int/e#0" in ids(hits)


@pytest.mark.parametrize("mode", MODES)
def test_licensed_member_gets_restricted_too_but_not_for_other_products(env, mode):
    cfg, qc = env
    assert "res/g#0" in ids(S.search(CHUNKS[6]["text"], k=10, principal=Principal.member("kafka"),
                                     mode=mode, cfg=cfg, qc=qc))
    assert "res/g#0" not in ids(S.search(CHUNKS[6]["text"], k=10, principal=Principal.member("github"),
                                         mode=mode, cfg=cfg, qc=qc))
    pg = S.search(CHUNKS[5]["text"], k=10, principal=Principal.member("kafka"), mode=mode, cfg=cfg, qc=qc)
    assert not (ids(pg) & {"res/f#0", "int/d#0"})  # postgres non-public chunks, kafka-only member


@pytest.mark.parametrize("mode", MODES)
def test_member_without_licenses_equals_public(env, mode):
    cfg, qc = env
    for c in CHUNKS:
        a = S.search(c["text"], k=10, principal=Principal.member(), mode=mode, cfg=cfg, qc=qc)
        b = S.search(c["text"], k=10, principal=PUBLIC, mode=mode, cfg=cfg, qc=qc)
        assert ids(a) == ids(b)


@pytest.mark.parametrize("mode", MODES)
def test_admin_can_read_everything(env, mode):
    cfg, qc = env
    hits = S.search("password keystore secrets", k=10, principal=ADMIN, mode=mode, cfg=cfg, qc=qc)
    assert "restricted" in levels(hits)


def test_filter_is_inside_the_qdrant_query_not_applied_after(env, monkeypatch):
    cfg, qc = env
    seen = []
    real = qc.query_points
    monkeypatch.setattr(qc, "query_points", lambda *a, **kw: (seen.append(kw["query_filter"]), real(*a, **kw))[1])
    # k=3 and the 3 nearest chunks to this question are restricted/internal: a post-filter would return < 3
    hits = S.search("rotate password pg_hba scram jaas keystore secrets", k=3, principal=PUBLIC, mode="dense",
                    cfg=cfg, qc=qc)
    assert len(hits) == 3 and levels(hits) == {"public"}
    cond = seen[0].must[0]
    assert cond.key == "access_level" and cond.match.any == ["public"]


def test_no_principal_means_public(env):
    cfg, qc = env
    assert levels(S.search("password keystore", k=10, mode="dense", cfg=cfg, qc=qc)) == {"public"}


def test_chunk_without_access_level_is_never_returned():
    idx = S.BM25Index([{"chunk_id": "n#0", "text": "secret thing", "title": "t"}])
    assert idx.search("secret", 5, ADMIN, load_config()) == []


def test_unknown_mode_is_an_error(env):
    cfg, qc = env
    with pytest.raises(ValueError, match="unknown mode"):
        S.search("x", mode="magic", cfg=cfg, qc=qc)


def test_product_and_access_filters_combine(env):
    cfg, qc = env
    for mode in MODES:
        hits = S.search("password secrets monitoring", k=10, product="kafka", principal=Principal.member("kafka"),
                        mode=mode, cfg=cfg, qc=qc)
        assert {h["product"] for h in hits} == {"kafka"}
        # asking for a product you hold no license for narrows to its public chunks only
        hits = S.search("password secrets monitoring", k=10, product="postgres", principal=Principal.member("kafka"),
                        mode=mode, cfg=cfg, qc=qc)
        assert levels(hits) == {"public"}


def test_qdrant_filter_and_python_rule_agree_on_every_chunk(env):
    """The two forms of the rule (Qdrant query for dense, allows() for BM25) must never drift apart."""
    cfg, qc = env
    everyone = ([PUBLIC, ADMIN, Principal.member(), Principal.member("kafka", "postgres")]
                + [Principal.member(p) for p in PRODUCTS])
    for who in everyone:
        points, _ = qc.scroll("test_search", scroll_filter=who.qdrant_filter(cfg), limit=100, with_payload=True)
        by_qdrant = {p.payload["chunk_id"] for p in points}
        by_python = {c["chunk_id"] for c in CHUNKS if who.allows(c, cfg)}
        assert by_qdrant == by_python, who


def _live_qdrant():
    try:
        qc = S.client(load_config())
        return qc if qc.collection_exists(load_config()["qdrant"]["collection"]) else None
    except Exception:
        return None


@pytest.mark.skipif(_live_qdrant() is None, reason="real Qdrant index is not running")
@pytest.mark.parametrize("mode", MODES)
def test_real_index_nobody_reads_beyond_their_licenses_for_any_eval_question(mode):
    cfg, qc = load_config(), _live_qdrant()
    qs = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").open(encoding="utf8")]
    for q in qs:
        for who in (PUBLIC, Principal.member(), Principal.member("github"), Principal.member("kafka", "postgres")):
            for h in S.search(q["question"], k=10, principal=who, mode=mode, cfg=cfg, qc=qc):
                assert h["access_level"] == "public" or h["product"] in who.licenses, (q["id"], who, h["chunk_id"])
