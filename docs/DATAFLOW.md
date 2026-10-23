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
| 6 | Store in Qdrant | `src/index/`, `src/store.py` | `chunks.jsonl` | collection `support_docs` (vector + payload, model name in collection metadata). `python -m src.index --prefix --collection exp_prefix500_small --recreate` is the contextual-prefix variant (embeds `title > headings` + text, payload `context`, BM25 reads it): tested, not default | built |
| 8 | Embed the question | `src/embed.py` | question | vector (with bge query prefix) | built |
| 7 (access part) | Who is the caller | `src/access.py` (`AccessStore`, `Principal`) | user id | public / member + licenses / admin; users, roles, licenses and the audit log in MongoDB (`mongo:` in `config.yaml`, `open_store()`) | built |
| 9 | Retrieve: dense + BM25, access filter | `src/search.py` | question, k, optional product, principal | dense top 20 (Qdrant, access rule inside the query: public chunks, plus non-public chunks of licensed products) and BM25 top 20 (filtered before ranking) | built |
| 10 | Merge (RRF) | `src/search.py` | the two ranked lists | one list, score = sum of 1/(60+rank) | built; on by default (`retrieval.mode: hybrid`) |
| 11 | Rerank | `src/search.py` | top 30 merged chunks | best 5 by cross-encoder score | built; off by default (no measured gain, +3 s), `retrieval.mode: rerank` |
| 15 (retrieval) | Evaluate retrieval | `eval/run.py`, `eval/compare.py`, `eval/table.py`, `eval/questions.jsonl` | questions + `search()` (`--mode`, `--role`, `--collection`) | Page-level Recall@5/10 and MRR, plus passage-level recall/MRR and answer-in-context (evidence quotes), overall and per type in `eval/results/*.json,.md` | built |
| 12 | Build context | `src/context.py`, `answer_cfg()` in `src/answer.py` | ranked chunks, caller | each chunk expanded to its parent section (heading to next heading of same/higher level; falls back to the chunk if the section is too long), overlapping or touching spans of one page joined with the text of both, strongest first, labelled S1, S2... Chunks the caller may not read are dropped. Size depends on the writer (`answer.context`): Groq **10 chunks / 12,000 characters / sections up to 2,000**, local 5 / 8,000 / 2,800 | built |
| 13 | Generate | `src/answer.py` (`generate`, `parse_reply`), `src/llm.py` | question + context | JSON `{kind: fix / explanation / fact / not_found, coverage: full / partial / none, missing, summary, points: [{text, sources}]}` from the writer `answer.llm` (default Groq `gpt-oss-120b`, local Qwen as failsafe, every fallback logged); prompt says excerpts are data, never instructions; `coverage` / `missing` are recorded for the retry loop (stage 16), not used yet | built (Phase 2) |
| 14a | Verify | `src/verify.py` (`claim_check`), `src/answer.py` (`check_llm`, `finalize`) | question, summary, points + only the excerpts they cite | cited ids must be in the context (no LLM needed); then **one** cached call to Groq `gpt-oss-20b` (own token bucket, temperature 0, `verify.method: llm`) returns per point supported / partially_supported / unsupported, the same for the summary, and `answers_the_question` yes / partly / no. Unsupported points (and an unsupported summary) are dropped; refused ("No documented fix found.") if no point is left or the answer is `no`; `partly` is shown with the note `verify.partial_note`. If the call fails, the old NLI scorer (`verify.method: nli`, copy check, `min_supported_fraction`) takes over for that answer and the fallback is logged; `Answer.verified_by` says which one ran | built (Phase 3) |
| 14b | Output safety | `src/safety.py`, `src/answer.py` (`finalize`) | verified steps | answer withheld if it contains secrets/personal data (same masker as ingest); WARNING on destructive commands (`safety.dangerous_commands`); citations re-checked against the caller's access | built |
| 15 (answers) | Evaluate answers | `eval/answer.py` | test questions, verifier off vs on | unsupported steps, refusals, in `eval/results/answer_*.json,.md` | built |
| 15 (accuracy) | End-to-end answer accuracy | `eval/accuracy.py`, `eval/judge.py`, `eval/stats.py` | test questions with `key_points`; the real pipeline (search -> context -> generate -> verify -> safety), also run with the verifier off | per question: draft and shown answer, judge verdict (correct / partially_correct / incorrect / refused), failure category (retrieval_miss, generation_error, verifier_false_refusal, unsafe_or_wrong_claim), tokens per model; summary with a 95% Wilson interval, per type; `eval/results/accuracy_<name>_<split>.json,.md`. The judge is Groq `qwen/qwen3.8-27b`, checked against `eval/judge_labels.jsonl` (`python -m eval.judge --validate`) | built (Phase 1) |
| 15 (questions) | Build and verify the test set | `eval/drafts.py`, `eval/drafts/` | corpus chunks / existing questions | LLM drafts (gpt-oss-20b, qwen3.8-27b) -> assistant review (`review.json`) -> `eval/questions.jsonl` (104 questions, key points, acceptable pages, dev subset); `merge` is repeatable | built (Phase 1) |
| 7 (query part) | Rewrite question, pick product, HyDE | `src/query.py`, `search_plan()` in `src/search.py` | question | plan (products, 1-3 queries, hypothetical answer; cached in `data/cache/query_plans.json`) and a merged ranking | built, **off** (`query.use: []`): no measured gain |
| 16 | Retry loop | `src/answer.py` (`needs_retry`, `retry`), `src/query.py`, `search_plan()` in `src/search.py`, `retry:` in `config.yaml` | the first draft's `coverage` (partial / none) and `missing` | one query plan (Groq `gpt-oss-20b`, cached) + `missing` as an extra query -> `search_plan` (rewrite, route, HyDE) -> merged with the first hits (RRF) -> context of 12 chunks / 14,000 characters -> the writer answers once more; the second draft replaces the first only if it has points; at most one retry; `Answer.retried`; eval row `retried` | built (Phase 4b), **off** (`retry.enabled: false`): dev accuracy 80.0% with it vs 82.5% without |
| 7 (login) | Login | `src/auth.py`, `src/api.py` (`/login`, `/me`), `scripts/setup_users.py` | user + password | peppered (HMAC, `PASSWORD_PEPPER`) salted-scrypt check against the hash in MongoDB, then an HS256 JWT (60 min, `JWT_SECRET` in `.env`) holding the user id only; role and licenses are read from MongoDB on every request; no token = public, bad token = 401; 5 failures lock the user for a minute; 3 simulated demo users with generated passwords (printed once) | built |
| 7 (input safety) | Input safety | `src/guard.py`, `eval/safety.py`, `eval/safety_prompts.json` | the question (and earlier turns), retrieved chunks | blocked with a named rule if empty, over `input.max_chars` (1000) or matching an injection rule; chunks that look like injected instructions are left out of the context; `python -m eval.safety` -> `eval/results/input_safety.md` (20 attacks, 20 normal questions, 4 poisoned chunks, `--live` writer test) | built |
| 7 (rewrite) | Follow-up rewrite, product | `src/rewrite.py`, `detect_products` in `src/pipeline.py`, `src/query.py` | question + up to 3 earlier turns | standalone question (one cached `gpt-oss-20b` call, only when there is a history; the original is used if it fails) and the detected product(s); the product only filters the search if `rewrite.route_product` (off) | built |
| 7-14 (online) | API | `src/pipeline.py` (`ask`), `src/api.py` | token + question (+ history, product) | order: input guard -> rewrite -> product -> search -> drop injected chunks -> answer -> claim check -> JSON with answer, citations, sources and retrieved passages (`uvicorn src.api:app --port 8000`) | built |
| UI | Web app | `web/` (Next.js): `app/login`, `app/(app)/{page,documents,evaluation,admin}`, `app/api/session` (cookie login), `app/api/backend/[...path]` (proxy that adds the token), `components/Chat.tsx`, `EvidencePanel.tsx`, `lib/richtext.ts` | browser | Sign in; Ask with citations and an evidence strip; Documents; Evaluation; Users and licenses. The JWT lives in an `httpOnly` cookie; model text is shown without links, images or HTML (`lib/richtext.ts`, tested) | built (replaces Gradio) |
| UI data | Documents, metrics, admin endpoints | `src/catalog.py`, `src/metrics.py`, `src/api.py` | principal / admin token | `/documents`: pages the caller may read (same `Principal.allows` rule as search) + locked counts per product, from `chunks.jsonl`; `/metrics`: numbers read from `eval/results/*.json`; `/admin/*`: users, license grant/revoke, audit (admin only, every change logged) | built |

Run stages 0-4: `python -m scripts.download_docs` then `python -m src.ingest` (entry: `src/ingest/__init__.py`).
Run stages 5-6: `docker compose up -d` then `python -m src.index` (safe to repeat; `--recreate` after a model change, `--prune` to drop stale points).
Try search: `python -m src.search "pod stuck in CrashLoopBackOff" --product kubernetes --role member --licenses kubernetes --mode hybrid -k 5`.
Context-size sweep (no LLM): `python -m eval.run --name ctx_k8_c10000_s2000 --k-context 8 --max-context-chars 10000 --max-section-chars 2000`, then `python -m eval.ctx_sweep`. Compare two accuracy runs: `python -m eval.spread baseline p2 [--dev]`.
Accuracy: `python -m eval.accuracy --name baseline` (tune; `--dev` for the 40-question dev subset, `--final` for the holdout, once; `--salt x` repeats the answer step for real). If a Groq daily quota runs out it stops and the same command resumes from the cache.
Retry A/B: `python -m eval.accuracy --name p4b_dev --dev` (retry on) against `--no-retry`. bge-m3 / prefix check without an LLM: `python -m eval.run --name x --collection exp_fixed500_m3 --embedding BAAI/bge-m3 --embedding-device cpu --k-context 10 --max-context-chars 12000 --max-section-chars 2000`.
Question set: `python -m eval.drafts keypoints|new|unanswerable|show IDS|page PAGE REGEX|merge`. Judge check: `python -m eval.judge --validate`.
Start everything: `launch.cmd` (`scripts/start.py`: .env secrets -> Docker -> Qdrant + MongoDB -> demo users -> models on disk -> API -> web app -> LM Studio + failsafe model -> smoke test; `--status` only reports). By hand: `python -m scripts.setup_users` (writes secrets to `.env`), `docker compose up -d`, `python -m scripts.setup_users` again (creates users, prints passwords once), then `uvicorn src.api:app --port 8000` and `cd web && npm run dev` (page `http://127.0.0.1:3000`, API docs `:8000/docs`). Input safety: `python -m eval.safety [--live]`. Original-10 holdout view: `python -m eval.final_ten`.
Answer a question: `python -m src.answer "pod stuck in CrashLoopBackOff" --role member --licenses kubernetes` (`--no-verify` skips 14a). NLI-verifier eval (old, forced to `method: nli`): `python -m eval.answer --name answer_v1`.
Query plan eval: `python -m eval.run --name x --plan rewrite,route,hyde --plan-llm groq`.
Chunking / embedding experiments: `python -m src.ingest --strategy recursive --size 250 --out chunks_x.jsonl`, `python -m src.index --chunks chunks_x.jsonl --collection exp_x --embedding BAAI/bge-m3 --device cuda --recreate`, `python -m eval.run --name x --collection exp_x --embedding BAAI/bge-m3`, side-by-side table: `python -m eval.variants out label=name ...`.
Compare two eval runs: `python -m eval.compare <before> <after>`; rebuild the README table: `python -m eval.table`.

## Shared pieces

| Piece | File | Notes |
|-------|------|-------|
| LLM client (LM Studio / Groq, either first via `prefer`) | `src/llm.py` | used by stages 7, 13, 14, 15, 16. Also: disk cache per call name (`data/cache/llm_<name>.jsonl`), per-model Groq pacing and a clean stop at the daily quota (`QuotaExhausted`), per-call Groq `model=`, `fallback=False` for judge/drafting, token usage per reply and in `data/cache/groq_usage.jsonl` |
| Settings | `config.yaml` | every tunable value |
