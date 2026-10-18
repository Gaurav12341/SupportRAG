# DECISIONS

One entry per real choice: what we chose, why, what else we considered.

## GPU vs CPU split (4 GB VRAM)

Checked with `nvidia-smi`: NVIDIA GTX 1650 Ti, 4096 MiB. Windows apps already hold
about 0.8-1.1 GB of it, so plan for roughly 3 GB free.

| Model | Runs on | Size | Why |
|-------|---------|------|-----|
| Qwen2.5-3B-Instruct, Q4_K_M (LM Studio) | **GPU** | about 2 GB weights + KV cache (estimate, not yet measured) | the only model that needs the GPU; generation is the slow step |
| bge-small-en-v1.5 (embedding) | CPU | 268 MB on disk | small; short texts are fast enough on CPU |
| ms-marco-MiniLM-L-6-v2 (reranker) | CPU | 183 MB on disk | small cross-encoder; reranks about 20 passages per question |
| nli-deberta-v3-small (NLI) | CPU | 1146 MB on disk | runs only on the final answer check |

- **Chose:** the LLM gets the GPU alone; everything else stays on CPU.
- **Why:** the LLM plus its KV cache takes most of the free VRAM, and CPU is fast enough for the three small models.
- **Considered:** embeddings on GPU (about 130 MB in fp16). Possible later if measured VRAM has room.
- **Measured (2026-10-18):** `nvidia-smi` showed 760 MiB used before loading Qwen and 3111 MiB
  after, so Qwen2.5-3B Q4_K_M costs about 2.3 GB. That leaves roughly 1 GB free, which is
  enough for the small embedding model on GPU if wanted, but not needed.

## Local models (pre-downloaded from Hugging Face)

| Role | Model | On-disk size |
|------|-------|--------------|
| Embedding | `BAAI/bge-small-en-v1.5` | 268 MB |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 183 MB |
| NLI | `cross-encoder/nli-deberta-v3-small` | 1146 MB |

Sizes are the Hugging Face cache folder sizes and may include more than one weight
format. Downloaded with `scripts/download_models.py`. Names live in `config.yaml`.
All three exist on Hugging Face as of 2026-10-18 (they downloaded).

## LLM client: LM Studio default, Groq failsafe

- **Chose:** one small client, `src/llm.py`. Default is LM Studio at `http://localhost:1234/v1`,
  model id `qwen2.5-3b-instruct` (Q4_K_M, taken from the server's model list; not loaded yet).
- **Fallback to Groq** only if the local server is unreachable, times out, or returns empty
  or invalid output. Each fallback is logged to `logs/fallbacks.log`.
- **Groq model:** `openai/gpt-oss-120b`, picked from Groq's models page on 2026-10-18.
  `llama-3.3-70b-versatile` is now listed as enterprise-only. **Not verified:** the page does
  not say whether gpt-oss-120b is free. A test call with the real key worked (answer in
  0.8 s), and the key's model list includes it, but that does not prove it is free. Check
  your Groq console; anything paid needs your approval.
- **Confirmed free (2026-10-18):** the account is on the Free plan with no paid billing.
  Limits for gpt-oss-120b as shown in the Groq console: 30 requests/min, 1,000 requests/day,
  8,000 tokens/min, 200,000 tokens/day. Over the limit the call fails (HTTP 429), it does not
  cost money.
- **What the limits mean:** 8k tokens/min is the tight one. A RAG prompt with 5 chunks may use
  2-4k tokens, so Groq handles only about 2-3 such calls a minute. Fine as a failsafe, but a
  full eval run should use the local model, not Groq. gpt-oss is a reasoning model, so its
  hidden reasoning also counts toward the token limits.
- **Models the key can see:** gpt-oss-120b, gpt-oss-20b, gpt-oss-safeguard-20b, qwen3.8-27b,
  allam-2-7b, two Llama Prompt Guard models, Whisper and Orpheus (speech). `scripts/check_llm.py`
  re-runs this check.
- **Considered:** `openai/gpt-oss-20b` (smaller, cheaper) as a lighter fallback.
- Only public docs and test questions may go to Groq. The key comes from `.env`.

## torch from the pytorch.org CPU index

- **Chose:** CPU-only torch from `download.pytorch.org/whl/cpu`, set in `pyproject.toml`.
- **Why:** PyPI's download servers ran at about 75 KB/s from this machine (measured with
  curl), versus about 15 MB/s for pytorch.org. PyPI's torch also pulls about 18 NVIDIA CUDA
  packages we do not need. After the change the full install took 52 seconds.
- **Gotcha:** uv's `[tool.uv.sources]` only applies to direct dependencies, so `torch` is
  listed as a direct dependency on purpose.
- **Considered:** a Defender exclusion (did not help; the slowness was the network).

## Project setup

- **venv:** local `.venv` with `uv` installed inside it; nothing installed globally.
- **Python:** 3.14 is the only version installed. Everything installed fine on it.
- **config.yaml** sits in the project root, as CLAUDE.md says. `configs/` exists as
  requested but is empty for now.
- **Makefile** targets `ingest`, `index`, `eval`, `ui` point at modules that do not exist yet.
  `make` is not installed on this machine (Windows); install it or run the commands by hand.
- **Chunk, retrieval and threshold values** in `config.yaml` are placeholders, not tuned.

## Ingestion (stages 1-4)

- **Sources and selection:** Kubernetes, GitHub Actions, Kafka and PostgreSQL pages picked by
  per-folder quotas in `configs/sources.yaml` (troubleshooting folders first), plus 200 Stack Overflow
  Q&A from the official API. Licenses in `docs/DATA_SOURCES.md`. *Considered:* scraping the live sites
  (slower, ruder, less clean than git repos); the Stack Overflow data dump (huge download).
- **Result:** Kubernetes 100, GitHub 94, PostgreSQL 78, Kafka 65 (all it has), Stack Overflow 200.
  Pages under 300 characters after cleaning are skipped (index/stub pages).
- **Parse:** repos give markdown, so only Hugo/Liquid tags are cleaned; PostgreSQL HTML and Stack
  Overflow bodies go through a small BeautifulSoup converter (headings, code blocks, tables kept).
  Links keep their text and lose the URL. *Considered:* `markdownify` (extra dependency, less control).
- **Masking:** regex rules in `src/ingest/clean.py`. Known token shapes (AWS, GitHub, Slack, Stripe/API
  keys, JWT, private keys, Bearer), `password=`/`token:` values that look random, emails, phones.
  Kept on purpose: localhost, example.com/org/net, IPs, versions, and placeholders (`xxxx`, `EXAMPLE`,
  `${VAR}`, `<token>`, `changeme`). Email regex ignores `action@v3.0.0` and `$TOKEN@host` (found as false
  positives in the first run). Tested with fake secrets only. Real docs contain almost none: 21 masked.
- **Chunking:** fixed 500-token windows, 50 overlap, counted with the bge-small tokenizer (max input 512).
  Ignores headings and sentences on purpose; improve later. Changed `config.yaml` from the 300 placeholder.
- **Access levels:** simulated, from `configs/access_rules.yaml`, first match wins (security/auth pages
  restricted; ops/admin pages internal; the rest public).
- **Doc types:** `troubleshooting` (path/title has debug, troubleshoot, errcodes), else the page's own
  type (concept, howto, tutorial, reference), `qa` for Stack Overflow. Rough rules, not verified.
- **No exact duplicate pages exist** in this selection (0 dropped); the logic is unit-tested.
- **Dependency added:** `beautifulsoup4`.

## Indexing and basic search (stages 5, 6, 8, 9)

- **Chose:** one Qdrant collection `support_docs`, cosine distance, 384-dim bge-small vectors, full chunk
  metadata + text in the payload. Code: `src/embed.py`, `src/store.py`, `src/index/`, `src/search.py`.
- **No duplicates on re-run:** the point id is a UUID made from the `chunk_id` (uuid5), so the same chunk
  always overwrites itself. A short hash of the text is also stored, so unchanged chunks are not
  embedded again and a changed chunk replaces its old version. *Considered:* wiping and rebuilding every
  time (slow on CPU, and loses the "re-run is cheap" property).
- **Model name check:** the embedding model name is saved in the collection's own `metadata`
  (`qdrant-client` 1.19 supports it), not in a side file, so it cannot drift from the vectors. Indexing
  and searching both compare it with `config.yaml` and raise `EmbeddingModelMismatch` with a fix-it
  message. Switching models needs `python -m src.index --recreate`.
- **Questions get bge's query prefix** ("Represent this sentence for searching relevant passages: ");
  documents do not. That is how bge-small was trained. Not measured yet (needs the eval set).
- **Stale points** (chunk removed from `chunks.jsonl`) are counted and reported, but only deleted with
  `--prune`, because deleting data needs your OK.
- **Payload indexes** on `product`, `access_level`, `source`, `doc_type` so filters stay fast. Access
  filtering itself is stage 9 proper and is not wired into `search()` yet.
- **Product filter values** are the 4 products (kubernetes, postgres, kafka, github). Stack Overflow chunks
  carry the product their question is about, so there is no "stackoverflow" product (it is `source`).
- **Qdrant client timeout 60 s** (default 5 s): the first calls after Docker starts took 2-6 s each.
- **Tests use Qdrant's in-memory mode**, so `pytest` does not need Docker.

## Test question set (stage 15, step 1)

- **Chose:** 40 questions in `eval/questions.jsonl` (10 exact error messages, 10 symptoms, 8 versions, 6 across
  products, 6 the docs cannot answer), all `verified=false` until you review them. Split: 30 `tune`,
  10 `holdout` (touch the holdout only for the final run).
- **Grounded in the corpus, not memory:** every answerable question cites the page, the section and a
  verbatim `evidence` quote; `tests/test_eval_questions.py` checks each quote exists in `chunks.jsonl`. Each
  unanswerable question lists `absent_terms` that the test proves occur nowhere in the corpus (e.g. PgBouncer,
  Terraform). First draft idea "logical replication" was dropped as unanswerable because the corpus covers it.
- **Labels are pages, not chunks:** `relevant` is a list of groups; any one page in a group satisfies it
  (alternates), and cross-product questions have 2 groups (one per product) that must both be found.
  Chunk ids change whenever chunking is retuned; page paths do not. *Considered:* chunk-level labels (precise
  but break on every re-chunk).
- **Holdout picked by hand before any retrieval ran**, 10 questions spread over all 5 types and 4 products
  (err-02/06/10, sym-04/09, ver-03/05, x-03, none-01/06). *Considered:* random split (could leave a type out).
- **Tickets as sources:** 10 questions have a Stack Overflow page among their answer pages (the stand-in "tickets"); the
  rest cite docs pages. Docs versions are whatever was downloaded (Kafka 4.3, Kubernetes v1.36-dev,
  PostgreSQL current = 18), so version questions are "as of this corpus".
- **Not measured yet:** no metric exists until the eval script is written (step 2, after "verified").

## Eval script and baseline (stage 15, step 2)

- **Chose:** `python -m eval.run` scores `src.search.search()` as it is today (dense only, no product or access
  filter) on the tuning split, top 10. Writes `eval/results/baseline_dense_tune.{json,md}`; the README table is
  copied from the `.md`. The holdout runs only with `--final`, and the script refuses unverified questions.
- **Metrics:** Recall@5, Recall@10, MRR. Recall = share of required page groups found (cross-product questions
  have 2); MRR = 1/rank of the first correct chunk. Ranks are over chunks, not de-duplicated pages, because that is
  what the later context builder will receive. *Considered:* de-duplicating pages first (hides crowding by one page).
- **Unanswerable questions are skipped for retrieval metrics** (no correct page). Their score will be "did it
  refuse", which needs stages 13-14.
- **Questions marked `verified=true`** after your explicit "verified all"; the project rule says to ask first.
- **Baseline reading:** n=26, Recall@5 = Recall@10 everywhere, so improvements must be judged on MRR and the
  cross-product row. Do not tune on `holdout`.

## Search improvements (stages 3, 9, 10, 11), one change at a time

Method: after each change, `python -m eval.run` on the tuning split (26 answerable questions), then
`python -m eval.compare` against the previous step. Keep a change only if it helps. Holdout untouched.
Full table: README Results. Per-question lists: `eval/results/compare_*.md`.

- **1. Heading-aware chunks: NOT kept (`chunking.strategy: fixed`).** *What:* split at markdown headings, pack
  sections up to 500 tokens, merge sections under 100 tokens into a neighbour, never cut a code block or table (an
  oversized table repeats its header), repeat the section heading when a section continues in a new chunk.
  *Result:* Recall@5 0.904 -> 0.808, Recall@10 0.904 -> 0.865, MRR 0.763 -> 0.753; 5 questions helped, 8 hurt.
  *Why it did not help:* 3816 chunks instead of 2602, so several small chunks of one page crowd the top 10, and the
  exact-error question err-09 lost its chunk. It did help version questions (MRR +0.232). *Considered:* tuning
  `min_tokens` (not tried: tuning on 26 questions is mostly noise). The code stays behind the config flag, tested.
  I re-scored it on top of hybrid and rerank before dropping it for good (README re-test rows): still no clear win.
  *Process note:* I kept a copy of the heading index as Qdrant collection `support_docs_headings` (vectors copied, no
  re-embedding) so this re-test needed no second 12-minute indexing run. After switching back, the fixed index
  reproduced the original baseline exactly (identical JSON summary).
- **2. BM25 + RRF: kept (`retrieval.mode: hybrid`).** *What:* `rank-bm25` (BM25Okapi) over title + text of every chunk,
  built in memory from Qdrant's payloads (so it can never disagree with the index); tokens = lowercase `\w+`. Dense
  top 20 + BM25 top 20 merged with Reciprocal Rank Fusion, `rrf_k = 60`.
  *Result:* MRR 0.763 -> 0.825, Recall@10 unchanged (0.904), Recall@5 0.904 -> 0.865 (one version question moved from
  rank 5 to 6); 7 helped, 4 hurt. *By type:* no gain on error_message (0.905 before and after, so the "BM25 wins on
  exact error messages" idea is **not supported** here: dense already found them), gains on symptom (+0.077) and
  cross_product (+0.160); the helped questions have distinctive literal words. Cost: negligible once the index is warm (median search 125 ms vs 124 ms for dense in the eval).
  *Considered:* weighted score fusion (needs tuning of weights, RRF has none); Qdrant sparse vectors (more moving
  parts). *Bug found while measuring:* `search()` made a new Qdrant client per call, which made the BM25 cache miss and
  rebuilt the index every search (1.1 s). Fixed with one cached client per process (now 125 ms).
- **3. Cross-encoder rerank: NOT enabled by default.** *What:* `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU) re-scores
  the top 30 merged candidates, the best 5 go to the answer step (`k_rerank_in: 30`, `k_context: 5`). The eval asks for
  10 so it stays comparable with the earlier rows. *Result vs hybrid:* MRR 0.825 -> 0.822, Recall@5 0.865 -> 0.904 (one
  question), Recall@10 unchanged; 7 helped, 5 hurt; median search 125 ms -> 3197 ms. That is no measurable gain for
  about 3 s of latency, so by the keep-only-if-it-helps rule it is off. *This is a close call and yours to flip:* set
  `retrieval.mode: rerank`. Two reasons to revisit: answer quality (not measured yet, retrieval metrics are page-level)
  and stage 14, where a calibrated relevance score is the natural signal for "refuse if unsure" (RRF scores are not
  calibrated). *Considered:* a smaller `k_rerank_in` (less latency, untested).
- **4. Access level enforced in the Qdrant query: kept (a requirement, not a quality tweak).** *What:* roles in
  `config.yaml` (`viewer` = public, `member` = public + internal, `admin` = all); `search(role=...)` builds a
  `access_level IN (...)` filter that is part of the Qdrant query, and the BM25 side filters before ranking, so hidden
  chunks never reach RRF or the reranker. Default role is `viewer` (least privilege); an unknown role raises an error
  instead of falling back to "everything"; a chunk with no `access_level` is never returned. The eval defaults to
  `--role admin` so rows stay comparable. *Cost, measured:* Recall@10 0.904 (admin) -> 0.846 (member) -> 0.692
  (viewer). All 6 tuning questions a viewer loses have only internal/restricted answer pages, i.e. a viewer correctly
  gets nothing relevant (the answer step must say so). *Tests:* a viewer gets only public chunks even when the question is
  the exact text of a restricted chunk, in all three modes; the filter sits in the Qdrant call (k = 3 returns 3 public
  chunks, which a filter applied after the search could not); and the real index is checked for all 40 questions as
  viewer and member (restricted never reaches member). *Considered:* filtering after retrieval (leaks into scores,
  returns fewer than k, one bug away from a leak); a separate collection per level.
  *Limit:* roles are simulated and nothing authenticates the caller yet (stage 7, login).

## Access model: public / member (per-product licenses) / admin

*Supersedes the `viewer` / `member` / `admin` role names in change 4 above; the filter-inside-the-query design stays.*
Your requirement: the app will later run inside organizations, whose product data is the company's own apps; public =
outside users, admin = super user who grants licenses, members = users licensed per product.

- **Chose:** three roles. `public` (not logged in): public chunks of all products. `member`: public chunks of all products
  + internal and restricted chunks of licensed products only. `admin`: everything, and the only role that may add
  users and grant/revoke licenses. Your answers to my two questions: an unlicensed product still shows its **public**-level
  docs to a member (like an outside user), and **restricted** is readable by licensed members too (not admin-only).
  Consequence: for a member, internal and restricted behave the same; the difference only matters to public users.
- **One rule, two forms** (`src/access.py`): `Principal.qdrant_filter()` goes inside the Qdrant query,
  `Principal.allows()` filters BM25 candidates before ranking. A test checks they select the same chunks for every role and
  license combination, so they cannot drift apart. Missing/unknown `access_level` or `product` is denied, even for admin.
- **Licenses in SQLite** (stdlib, one file `data/access.db`, tables users / licenses / audit). *Considered:* a YAML file
  (no audit, hand-edited), Qdrant payloads (mixes who-can-see with what-is-indexed). Every grant/revoke is logged with the
  actor. A member cannot self-grant; the first admin is created by `bootstrap_admin` from a setup script, never via a request.
  Revoking takes effect on the next search (nothing is cached per user).
- **Fail closed:** unknown role/product raises; unknown or missing user is `public`; the public role cannot carry licenses.
- **Measured (hybrid, tune split):** admin = member licensed for all 4 = Recall@10 0.904; member with github only 0.712;
  public 0.692. Row labels are in README Results 4a-4d. The earlier `viewer`/`member`(public+internal) result files
  `step4_hybrid_*` are kept but no longer used.
- **Not built:** login (stage 7; will supply the `user_id`), HTTP endpoints for the admin dashboard (UI comes later),
  rate limits, license expiry/seats. In a real deployment the access level of a chunk should come from the source
  system's own metadata; the path rules are a stand-in.
