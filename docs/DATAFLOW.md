# DATAFLOW

## Pipeline (16 stages)

```
OFFLINE (once, before questions)
  1 Parse docs
  2 Clean + dedupe + mask secrets/personal data
  3 Chunk
  4 Add metadata + access level
  5 Embed
  6 Store in Qdrant

ONLINE (every question)
  7  Login, input safety check, rewrite question, pick product, HyDE (optional)
  8  Embed the question
  9  Retrieve: meaning search + keyword search (BM25), with access filter
  10 Merge results (RRF)
  11 Rerank
  12 Build context
  13 Generate answer with citations
  14 Verify answer, output safety check, refuse if unsure
  15 Evaluate (test questions + metrics)
  16 Agentic retry loop (optional, last)
```

## Stage table

| # | Stage | File | Input | Output | Status |
|---|-------|------|-------|--------|--------|
| 0 | Download | `scripts/download_docs.py` | `configs/sources.yaml` | `data/raw/` | built |
| 1 | Parse | `src/ingest/parse.py` | `data/raw/` | pages (markdown text) | built |
| 2 | Clean, dedupe, mask | `src/ingest/clean.py` | pages | clean pages, mask counts | built |
| 3 | Chunk | `src/ingest/chunk.py` | clean pages | ~500-token chunks | built |
| 4 | Metadata + access level | `src/ingest/metadata.py`, `configs/access_rules.yaml` | chunks | `data/processed/chunks.jsonl`, `pages.jsonl`, `ingest_report.json` | built |
| 5 | Embed | `src/embed.py` | chunk text | 384-dim normalized vectors (CPU) | built |
| 6 | Store in Qdrant | `src/index/`, `src/store.py` | `chunks.jsonl` | collection `support_docs` (vector + payload, model name in collection metadata) | built |
| 8 | Embed the question | `src/embed.py` | question | vector (with bge query prefix) | built |
| 9 | Retrieve (dense only so far) | `src/search.py` | question, k, optional product | top-k chunks with score | basic version built; BM25 and access filter not yet |
| 7, 10-16 | rest of the pipeline | – | – | – | not built yet |

Run stages 0-4: `python -m scripts.download_docs` then `python -m src.ingest` (entry: `src/ingest/__init__.py`).
Run stages 5-6: `docker compose up -d` then `python -m src.index` (safe to repeat; `--recreate` after a model change, `--prune` to drop stale points).
Try search: `python -m src.search "pod stuck in CrashLoopBackOff" --product kubernetes -k 5`.

## Shared pieces

| Piece | File | Notes |
|-------|------|-------|
| LLM client (LM Studio, Groq failsafe) | `src/llm.py` | used by stages 7, 13, 14, 16 |
| Settings | `config.yaml` | every tunable value |
