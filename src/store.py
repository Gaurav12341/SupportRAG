"""Qdrant helpers shared by indexing (stage 6) and search (stage 9)."""
import uuid

from qdrant_client import QdrantClient, models

DISTANCE = models.Distance.COSINE


class EmbeddingModelMismatch(RuntimeError):
    pass


def client(cfg):
    return QdrantClient(url=cfg["qdrant"]["url"], timeout=60)


def point_id(chunk_id):
    """Same chunk_id always gives the same point id, so re-running overwrites instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def stored_model(qc, collection):
    """Embedding model name saved in the collection's metadata, or None if it is not there."""
    return (qc.get_collection(collection).config.metadata or {}).get("embedding_model")


def check_model(qc, cfg):
    """Stop with a clear error if the collection was built with a different embedding model."""
    collection, want = cfg["qdrant"]["collection"], cfg["models"]["embedding"]
    if not qc.collection_exists(collection):
        raise RuntimeError(f"Collection '{collection}' does not exist. Run `python -m src.index` first.")
    have = stored_model(qc, collection)
    if have != want:
        raise EmbeddingModelMismatch(
            f"Collection '{collection}' was built with embedding model {have!r}, but config.yaml says "
            f"{want!r}. Embeddings from different models are not comparable. Re-index with the new model "
            f"(`python -m src.index --recreate`) or set models.embedding back to {have!r}.")
