# SupportRAG

## What it is

A support and troubleshooting assistant. Ask about an error or symptom and it answers
with steps that cite the docs. If the docs have no fix, it says so instead of guessing.
Docs: Kubernetes, PostgreSQL, Kafka, GitHub Docs, plus some Stack Overflow Q&A as
stand-in tickets. Access levels (public / internal / restricted) are **simulated** on
public docs. Free and local only (4 GB GPU). Pipeline details: `docs/DATAFLOW.md`.

## How to run

Stages 1-6 (ingest, embed, store) and a basic dense search are built; the rest is not.

```
python -m venv .venv
.venv\Scripts\python -m pip install uv
.venv\Scripts\uv sync --active
.venv\Scripts\python -m scripts.download_models
```

Build the corpus (data sources and licenses: `docs/DATA_SOURCES.md`):

```
.venv\Scripts\python -m scripts.download_docs   # once: clones/fetches into data/raw/
.venv\Scripts\python -m src.ingest              # parse, clean, chunk, metadata -> data/processed/
docker compose up -d                            # Qdrant on :6333
.venv\Scripts\python -m src.index              # embed + store in Qdrant; safe to re-run
.venv\Scripts\python -m src.search "pod stuck in CrashLoopBackOff" --product kubernetes
.venv\Scripts\python -m pytest
```

Copy `.env.example` to `.env` and set `GROQ_API_KEY` (failsafe only).
Start the LM Studio server and load `qwen2.5-3b-instruct`.
`make up | ingest | index | eval | ui` (`make` is not installed on this machine yet).

## Results

Retrieval/answer metrics: none yet; they will be copied from `eval/results/`.

Ingest output (from `data/processed/ingest_report.json`, run 2026-10-18):

| Source | Pages | Chunks |
|--------|------:|-------:|
| Kubernetes | 100 | 572 |
| GitHub Docs (Actions) | 94 | 366 |
| Kafka | 65 | 702 |
| PostgreSQL | 78 | 512 |
| Stack Overflow Q&A | 200 | 450 |
| **Total** | **537** | **2602** |

Secrets / personal data masked: 21 (19 emails, 2 secret values). Chunks by simulated access level:
public 1749, internal 596, restricted 257. Chunking: 500 tokens, 50 overlap.

Licenses and attribution: Kubernetes and GitHub Docs CC BY 4.0, Kafka Apache 2.0, PostgreSQL License,
Stack Overflow CC BY-SA 4.0 (see `docs/DATA_SOURCES.md`).

## Indexing and search (stages 5, 6, 8, 9 basic)

- 2602 chunks embedded with `BAAI/bge-small-en-v1.5` (CPU) and stored in Qdrant collection `support_docs`
  with their metadata. Re-running `src.index` embeds nothing new and creates no duplicates (tested).
- The embedding model name is stored in the collection. Search and indexing stop with
  `EmbeddingModelMismatch` if `config.yaml` names a different model.
- `src.search.search(question, k, product)` returns the top-k chunks. Dense (meaning) search only for now.
- No retrieval metrics yet: there is no eval set. Example searches were read by eye only.
- Known issue: Stack Overflow titles/text still contain HTML entities such as `&quot;` (ingest cleanup TODO).
