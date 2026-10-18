"""Stage 5/8: embed text with the model named in config.yaml (bge-small-en-v1.5, CPU)."""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from src.llm import load_config

# bge models are trained to see this prefix on questions (not on documents).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def model_name(cfg=None):
    return (cfg or load_config())["models"]["embedding"]


@lru_cache(maxsize=1)
def _model(name, device):
    # models are pre-downloaded by scripts/download_models.py; stay offline
    return SentenceTransformer(name, device=device, local_files_only=True)


def embed_docs(texts, cfg=None, batch_size=32):
    cfg = cfg or load_config()
    m = _model(model_name(cfg), cfg["models"]["device"])
    return m.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)


def embed_query(question, cfg=None):
    return embed_docs([QUERY_PREFIX + question], cfg)[0]
