"""Stage 5/8: embed text with the model named in config.yaml (bge-small-en-v1.5, CPU by default).

`models.embedding_device` (optional) overrides `models.device` for this model only, e.g. to index on the GPU while
LM Studio is stopped. On cuda the model runs in fp16."""
import re
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from src.llm import load_config

# bge models are trained to see this prefix on questions (not on documents).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def model_name(cfg=None):
    return (cfg or load_config())["models"]["embedding"]


def query_prefix(name):
    """Only the English bge v1.5 models were trained with the instruction on questions; bge-m3 and others take none."""
    return QUERY_PREFIX if re.fullmatch(r"BAAI/bge-.+-en-v1\.5", name) else ""


def embedding_device(cfg):
    return cfg["models"].get("embedding_device") or cfg["models"]["device"]


@lru_cache(maxsize=2)
def _model(name, device):
    # models are pre-downloaded (scripts/download_models.py, or snapshot_download); stay offline
    kw = {"model_kwargs": {"torch_dtype": "float16"}} if device.startswith("cuda") else {}
    m = SentenceTransformer(name, device=device, local_files_only=True, **kw)
    m.max_seq_length = min(m.max_seq_length, 1024)  # bge-m3 allows 8192; chunks are at most ~500 bge-small tokens
    return m


def embed_docs(texts, cfg=None, batch_size=32):
    cfg = cfg or load_config()
    m = _model(model_name(cfg), embedding_device(cfg))
    return m.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)


def embed_query(question, cfg=None):
    cfg = cfg or load_config()
    return embed_docs([query_prefix(model_name(cfg)) + question], cfg)[0]
