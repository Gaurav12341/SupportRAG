"""Stages 5-6 (offline): embed every chunk and store it in Qdrant. Run with `python -m src.index`.

Re-running is safe: a point's id comes from its chunk_id, so the same chunk overwrites itself.
Chunks whose text is unchanged are not embedded again.

`prefix=True` (python -m src.index --prefix) is the contextual-prefix variant (Phase 4c in docs/IMPROVEMENT_PLAN.md): the embedded text
is "title > heading > subheading" + the chunk text, and the payload gets that path as `context` (BM25 reads it too). The shown text
(`text`) is unchanged.
"""
import hashlib
import json
from pathlib import Path

from qdrant_client import models

from src.context import heading_path, load_pages
from src.embed import embed_docs
from src.llm import load_config
from src.store import DISTANCE, check_model, client, point_id

ROOT = Path(__file__).resolve().parent.parent.parent
BATCH = 64


def text_hash(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()[:16]


def read_chunks(cfg, name="chunks.jsonl"):
    path = ROOT / cfg["paths"]["processed"] / name
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line.strip()]


def context_line(chunk, pages):
    """"title > heading > subheading" for a chunk, from the headings above its first character in the page ("" if it cannot be located)."""
    page = pages.get(chunk["source_path"], "")
    pos = page.find(chunk["text"])
    parts = [chunk["title"]] + (heading_path(page, pos) if pos >= 0 else [])
    return " > ".join(p for i, p in enumerate(parts) if i == 0 or p != parts[i - 1])  # the page's # heading usually repeats its title


def existing_hashes(qc, collection):
    """{point id: text hash} for everything already stored."""
    out, offset = {}, None
    while True:
        points, offset = qc.scroll(collection, limit=1000, offset=offset, with_payload=["text_hash"], with_vectors=False)
        out.update({str(p.id): p.payload.get("text_hash") for p in points})
        if offset is None:
            return out


def run(recreate=False, prune=False, chunks_file="chunks.jsonl", collection=None, embedding=None, device=None, prefix=False):
    """`chunks_file`, `collection`, `embedding` and `device` override the defaults, for chunking / embedding experiments."""
    cfg = load_config()
    if collection:
        cfg["qdrant"]["collection"] = collection
    if embedding:
        cfg["models"]["embedding"] = embedding
    if device:
        cfg["models"]["embedding_device"] = device
    collection, model = cfg["qdrant"]["collection"], cfg["models"]["embedding"]
    qc = client(cfg)
    chunks = read_chunks(cfg, chunks_file)
    if prefix:
        pages = load_pages(cfg)
        chunks = [{**c, "context": context_line(c, pages)} for c in chunks]
    embedded = lambda c: f"{c['context']}\n\n{c['text']}" if prefix else c["text"]  # what is embedded (and hashed)
    stats = {"chunks": len(chunks)}

    if recreate and qc.collection_exists(collection):
        qc.delete_collection(collection)
    if not qc.collection_exists(collection):
        dim = len(embed_docs(["dimension probe"], cfg)[0])
        qc.create_collection(collection, vectors_config=models.VectorParams(size=dim, distance=DISTANCE),
                             metadata={"embedding_model": model, "dim": dim})
        stats["created_collection"] = True
    check_model(qc, cfg)  # refuses to mix vectors from two models
    for field in ("product", "access_level", "source", "doc_type"):  # filters; safe to repeat
        qc.create_payload_index(collection, field, models.PayloadSchemaType.KEYWORD)

    have = existing_hashes(qc, collection)
    todo = [c for c in chunks if have.get(point_id(c["chunk_id"])) != text_hash(embedded(c))]
    stats["already_up_to_date"] = len(chunks) - len(todo)
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        vecs = embed_docs([embedded(c) for c in batch], cfg)
        qc.upsert(collection, points=[
            models.PointStruct(id=point_id(c["chunk_id"]), vector=v.tolist(),
                               payload={**c, "text_hash": text_hash(embedded(c))})
            for c, v in zip(batch, vecs)])
        print(f"  embedded {min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
    stats["embedded_now"] = len(todo)

    keep = {point_id(c["chunk_id"]) for c in chunks}
    stale = [i for i in have if i not in keep]
    stats["stale_in_qdrant"] = len(stale)
    if prune and stale:
        qc.delete(collection, points_selector=models.PointIdsList(points=stale))
        stats["pruned"] = len(stale)
    stats["points_in_collection"] = qc.count(collection, exact=True).count
    return stats
