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
| 3 | Chunk | `src/ingest/chunk.py` | clean pages | ~500-token chunks (`fixed` windows, default; `headings` and `recursive` options, off: no gain, see DECISIONS) | built |
| 4 | Metadata + access level | `src/ingest/metadata.py`, `configs/access_rules.yaml` | chunks | `data/processed/chunks.jsonl`, `pages.jsonl`, `ingest_report.json` | built |
| 5 | Embed | `src/embed.py` | chunk text | 384-dim normalized vectors (CPU; `models.embedding_device` can put it on the GPU, fp16). bge-m3 (1024-dim, no query prefix) tested, not default | built |
| 6 | Store in Qdrant | `src/index/`, `src/store.py` | `chunks.jsonl` | collection `support_docs` (vector + payload, model name in collection metadata) | built |
| 8 | Embed the question | `src/embed.py` | question | vector (with bge query prefix) | built |
| 7 (access part) | Who is the caller | `src/access.py` (`AccessStore`, `Principal`) | user id | public / member + licenses / admin; licenses in `data/access.db`; login itself not built | roles and licenses built, login not built |
| 9 | Retrieve: dense + BM25, access filter | `src/search.py` | question, k, optional product, principal | dense top 20 (Qdrant, access rule inside the query: public chunks, plus non-public chunks of licensed products) and BM25 top 20 (filtered before ranking) | built |
| 10 | Merge (RRF) | `src/search.py` | the two ranked lists | one list, score = sum of 1/(60+rank) | built; on by default (`retrieval.mode: hybrid`) |
| 11 | Rerank | `src/search.py` | top 30 merged chunks | best 5 by cross-encoder score | built; off by default (no measured gain, +3 s), `retrieval.mode: rerank` |
| 15 (retrieval) | Evaluate retrieval | `eval/run.py`, `eval/compare.py`, `eval/table.py`, `eval/questions.jsonl` | questions + `search()` (`--mode`, `--role`, `--collection`) | Page-level Recall@5/10 and MRR, plus passage-level recall/MRR and answer-in-context (evidence quotes), overall and per type in `eval/results/*.json,.md` | built |
| 12 | Build context | `src/context.py` | ranked chunks, caller | up to ~8000 chars: each chunk expanded to its parent section (heading to next heading of same/higher level; falls back to the chunk if > 2800 chars), overlapping or touching spans of one page joined with the text of both, strongest first, labelled S1, S2... Chunks the caller may not read are dropped | built |
| 13 | Generate | `src/answer.py` (`generate`), `src/llm.py` | question + context | JSON `{steps: [{step, sources}]}` from the local LLM (Groq if unusable); prompt says excerpts are data, never instructions | built |
| 14a | Verify | `src/verify.py`, `src/answer.py` (`verify_steps`) | steps + the context they cite | per step: cited ids must be in the context; NLI (`nli-deberta-v3-small`, CPU) entailment of the step by the cited text, or the step is >= 70% copied (word triples) from it; unsupported steps dropped; "No documented fix found." if too few remain | built |
| 14b | Output safety | `src/safety.py`, `src/answer.py` (`finalize`) | verified steps | answer withheld if it contains secrets/personal data (same masker as ingest); WARNING on destructive commands (`safety.dangerous_commands`); citations re-checked against the caller's access | built |
| 15 (answers) | Evaluate answers | `eval/answer.py` | test questions, verifier off vs on | unsupported steps, refusals, in `eval/results/answer_*.json,.md` | built |
| 7 (query part) | Rewrite question, pick product, HyDE | `src/query.py`, `search_plan()` in `src/search.py` | question | plan (products, 1-3 queries, hypothetical answer; cached in `data/cache/query_plans.json`) and a merged ranking | built, **off** (`query.use: []`): no measured gain |
| 7 (login, input safety), 16 | rest of the pipeline | – | – | – | not built yet |

Run stages 0-4: `python -m scripts.download_docs` then `python -m src.ingest` (entry: `src/ingest/__init__.py`).
Run stages 5-6: `docker compose up -d` then `python -m src.index` (safe to repeat; `--recreate` after a model change, `--prune` to drop stale points).
Try search: `python -m src.search "pod stuck in CrashLoopBackOff" --product kubernetes --role member --licenses kubernetes --mode hybrid -k 5`.
Answer a question: `python -m src.answer "pod stuck in CrashLoopBackOff" --role member --licenses kubernetes` (`--no-verify` skips 14a). Eval: `python -m eval.answer --name answer_v1`.
Query plan eval: `python -m eval.run --name x --plan rewrite,route,hyde --plan-llm groq`.
Chunking / embedding experiments: `python -m src.ingest --strategy recursive --size 250 --out chunks_x.jsonl`, `python -m src.index --chunks chunks_x.jsonl --collection exp_x --embedding BAAI/bge-m3 --device cuda --recreate`, `python -m eval.run --name x --collection exp_x --embedding BAAI/bge-m3`, side-by-side table: `python -m eval.variants out label=name ...`.
Compare two eval runs: `python -m eval.compare <before> <after>`; rebuild the README table: `python -m eval.table`.

## Shared pieces

| Piece | File | Notes |
|-------|------|-------|
| LLM client (LM Studio / Groq, either first via `prefer`) | `src/llm.py` | used by stages 7, 13, 14, 16 |
| Settings | `config.yaml` | every tunable value |
