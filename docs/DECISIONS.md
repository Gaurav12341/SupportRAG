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
- **Licenses in SQLite** (stdlib, one file `data/access.db`, tables users / licenses / audit). *Superseded 2026-10-23: now MongoDB, see "Web app" below.* *Considered:* a YAML file
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

## Answer stage: context, generation, verifier, output safety (stages 12-14)

- **Context (stage 12).** *Chose:* take the top `k_context` (5) hybrid hits, expand each to its parent section (nearest
  heading above the chunk to the next heading of the same or higher level, found in `pages.jsonl`), merge sections of the
  same page that overlap, keep search order (strongest first), stop at 8000 characters. A section longer than 2800
  characters falls back to the chunk plus its heading, because LM Studio's context is small (3B model, 4 GB GPU).
  Sizes are in characters (about 4 per token), not tokens: simpler, and enough for a budget. *Why parent sections:*
  fixed 500-token windows cut procedures in half. *Considered:* neighbour chunks, whole pages (up to 170k characters).
  *Limit:* `#` lines inside code fences are not treated as headings; a page with no headings (some Stack Overflow
  answers) becomes one section, so it is cut by the 2800 cap.
- **Short labels, real ids shown.** The model cites `S1..S5`; answers and the eval show the real chunk ids. A 3B model
  copies long ids like `kubernetes/tasks/debug/_index.md#0` badly. A literal chunk id is also accepted if it is in the context.
- **JSON schema output, not free text.** *Chose:* `response_format=json_schema` with `{steps: [{step, sources[]}]}` (LM
  Studio and Groq both accept it). *Why:* with a plain "end each step with [S1]" prompt the 3B model often skipped
  citations. I tried the label at the end, the label at the start, and an example; each changed behaviour, none was
  reliable, and the example got copied into an answer. With the schema every step has a source. An empty list is the
  model saying "no fix". A reply that is not that JSON counts as unusable, so the client falls back to Groq.
- **Verifier.** Two checks per step: (1) every cited id must be one of the chunks in the context (anything else was
  invented, or may be a chunk the caller cannot read), (2) `cross-encoder/nli-deberta-v3-small` (CPU) scores whether the
  cited text entails the step; the cited sections are cut into ~1200-character windows and the best window counts.
  Unsupported steps are dropped; if none are left, or fewer than `min_supported_fraction` (0.5) are supported, the answer
  is "No documented fix found." *Considered:* an LLM judge (slower, and Groq is only the failsafe); keeping unsupported
  steps with a flag (the point is not to guess).
- **NLI threshold 0.3 (was a 0.5 placeholder).** Picked on the **tune** split only. Step scores are bimodal (first run:
  51 of 87 below 0.1, 21 above 0.5). At 0.5, 18 of 26 answerable questions were refused; from 0.1 to 0.4 the count only
  moved 12 -> 15, so 0.3 sits on the plateau. I checked the 41 steps scoring below 0.1 against all excerpts (a one-off script, not saved, so not a README number): 35 are
  supported by none (generic advice the model made up, such as "check your VPN"), only 6 are real facts cited to the wrong
  excerpt. So the low scores are mostly correct rejections, not NLI being too strict. The 0.5 run is kept as
  `answer_v1_tune.*`. *Limit:* NLI handles imperative steps ("Restart the server") less well than statements;
  steps copied word for word from the docs scored 0.43-0.84 in a spot check. Nobody has labelled steps by hand, so the
  threshold is not validated against a human.
- **Output safety.** Secrets / personal data: the answer is **withheld** (not redacted) if the ingest masker finds
  anything in it; the docs are already masked, so a hit means the model produced it. Dangerous commands (`kubectl delete`,
  `DROP TABLE|DATABASE|SCHEMA`, `TRUNCATE`, `kafka-topics ... --delete`) get a WARNING line under the step; the patterns
  live in `config.yaml`. Citations: only context chunks that `Principal.allows()` are cited, checked again at the end even
  though search already filters (defence in depth); a step left with no readable citation counts as unsupported.
  In the tune run no generated step contained a dangerous command or a secret, so these two are covered by unit tests
  only, not by eval numbers.
- **Prompt injection.** Excerpts are wrapped in `<doc>` tags, the system prompt says they are data and to ignore
  instructions inside them, and a `</doc` inside an excerpt is neutralised so it cannot close the tag. Unit-tested; **not**
  tested against a real attack corpus.
- **How the eval compares off and on.** Each question is generated once; the same draft is finalized with the verifier off
  and on, so only the verifier differs. "Unsupported steps" uses the verifier's own NLI score, so it is 0 with the verifier
  on **by construction**; the informative parts are the OFF column, the refusals, and the independent check ("steps with a
  command word not in the docs", which does not use NLI). A human step-level judgement would be better.
- **Holdout not used.** You asked about "the 6 unanswerable questions"; only 4 are in the tune split, 2 are holdout. The
  holdout is for one final run and the pipeline still has open parts (stages 7 and 16), so these numbers cover the 4 tune
  questions. *Open question for you:* run the holdout now, or at the very end?

## Over-refusals: what was tried (answer stage)

Goal: fewer answerable questions refused by the verifier (14 of 26 in `answer_v2`). Findings first, then what was kept.

- **Why the 14 were refused (checked by hand against the labelled evidence quotes, tune split).** In 3 the right page was
  not retrieved at all (refusing is correct). In about 5 the page was retrieved but the exact passage was not in the top 10 (**partly wrong, see the next section: a bug in my context builder explained some of these**)
  chunks (`sym-02`, `sym-03`, `x-01`, `x-05`, `x-06`): a **retrieval** problem hidden by the page-level retrieval eval, not fixable
  here. In the rest the passage was in the context but the 3B model paraphrased or added advice. So at most about 5 to 6 of the
  14 can be recovered by the answer stage.
- **Kept: copy check in the verifier.** NLI scored word-for-word steps (code lines, version sentences, list items) at 0.00-0.06,
  so the verifier rejected steps copied straight from the docs. A step is now also supported if at least 70% of its word triples
  appear in the cited text (`min_copied_trigrams`). On the tune data, steps from the 4 unanswerable questions reach at most 0.29,
  verbatim copies 0.73-1.00. *Limit:* 0.7 was chosen by looking at that tune data; it proves the step was copied, not that it is
  relevant to the question.
- **Tried, reverted: "stay close to the excerpts' wording" prompt.** Unsupported steps in the off column went 51/81 -> 44/85 in
  one run, then 58/97 and 55/91 in two more with the same prompt. Not a reliable gain, so the original prompt is back.
- **Tried, reverted: `min_supported_fraction` 0.5 -> 0.4.** Would rescue 2 questions in the stored scores but puts
  `none-03` (1 of 3 steps supported, a true but irrelevant doc sentence) on the edge, and a live run did not refuse fewer.
- **Run-to-run noise is about +-2 questions.** Answerable refusals in five runs of near-identical code: 14, 13, 13, 15, 15 (then 14
  on the final config). The model is sampled at temperature 0.1, so one question flipping is not a result. Any change smaller
  than that needs more questions or repeated runs to judge.
- **Not done (would help most):** (1) retrieval that returns the exact passage, not only the right page (e.g. smaller chunks, or
  the reranker, re-tested with a passage-level metric); (2) a relevance check, so a supported-but-irrelevant sentence cannot
  rescue an answer, which would allow a lower fraction; (3) a stronger local model if the GPU allows.

## Chunking, embedding and retrieval experiments (passage level)

Question from you: is the answer stage starved because chunking, embedding or retrieval is weak? Method: added **passage-level** metrics
to `eval/run.py` (the labelled evidence quote must be inside a retrieved chunk, and inside the context the answer step builds from the top 5).
A chunk counts if it is from the right page and holds at least half of the quote's word triples, so a quote cut by a chunk boundary still counts.
Chunking-independent, but bigger chunks hold evidence more easily, so average chunk size is reported next to it. 52 evidence items on the tuning
split: one item = 0.019, differences under about 0.05 are noise. Holdout untouched.

- **Chose: keep fixed 500-token chunks.** Tried fixed 250, recursive 500/250 (new `chunk_recursive`: headings, blank lines, lines, sentences,
  words; every chunk an exact page slice) and heading-aware 500/250 with bge-small and hybrid retrieval. None beat fixed 500 on passage recall@10
  (0.750); 250-token variants lose recall because more, smaller chunks crowd the top 10. Recursive was not better than plain fixed windows.
  *Not tried:* small-to-big (search small chunks, return the parent section), contextual prefixes, a different `k`.
- **Embedding: bge-m3 is better but modestly; not made the default (your call).** Same fixed-500 chunks: page MRR 0.825 -> 0.897, answer-in-context
  0.635 -> 0.712, passage recall@10 0.750 -> 0.769. Costs: 40-minute index build here, a 568M-parameter model, 1024-dim vectors, and at question
  time it must run on CPU because LM Studio's model needs the 4 GB GPU. End to end it did not change the answers (15 vs 14 of 26 refused,
  noise). CLAUDE.md names bge-small, so switching is a decision for you. *Considered:* `bge-base-en-v1.5` (not run).
- **`text-embedding-3-small`: not used.** Paid and cloud-hosted (CLAUDE.md: free and local only, ask before anything paid).
- **Reranker: stays off.** At passage level it raises recall@10 (0.750 -> 0.788) but lowers passage MRR (0.619 -> 0.467) and adds no answer-in-context.
- **Bug found and fixed in my context builder (stage 12).** Neighbouring chunks overlap by 50 tokens by design. The builder merged an overlapping hit
  into the previous item but only recorded its id, not its text, so a passage ranked 2nd could vanish from the context. Now overlapping or touching
  spans on the same page are joined into one item (or, if the join would exceed twice `max_section_chars`, the later hit is kept with the already-shown
  part cut off). Regression test in `tests/test_answer.py`. Effect: answer-in-context for the baseline 0.577 -> 0.635. The earlier answer-quality
  numbers (`answer_v1`..`v7`) were measured with the bug and are kept only as history; the README uses `answer_v8_*`.
- **Where the answer quality is lost now (bge-m3 run, tuning split).** Evidence fully in the context for 17 of 26 questions, yet 7 of those were still
  refused; evidence missing for 6 (5 refused, correct). So generation faithfulness (3B model plus a strict verifier), not retrieval, is the main limit.
  Cheapest next steps: a stronger generator (Groq as primary needs your OK), or a step-level human label set to check the NLI threshold.
- **GPU:** the venv's torch was the CPU build (pinned in `pyproject.toml` so the GPU stays free for LM Studio). For indexing I installed
  `torch==2.14.1+cu126` into `.venv` only with `uv pip install --no-deps`; `pyproject.toml` and `uv.lock` are unchanged, so `uv sync` would put the CPU build back.
  Config key `models.embedding_device` (fp16 on cuda) is new; default stays `models.device: cpu`. The GTX 1650 Ti indexed bge-small at 13 chunks/s and bge-m3
  at about 1 chunk/s. Both cannot run with the LLM loaded at once.
- **Experiment hygiene.** `python -m src.ingest --out FILE` writes only that chunks file. (My first attempt overwrote `chunks.jsonl`; I regenerated it and
  checked it is identical to what Qdrant holds, hash for hash.) Collections `exp_*` (six bge-small, one bge-m3) are left in Qdrant for re-use; I deleted only
  my own half-built `exp_fixed250_m3`. Chunk files `data/processed/chunks_*.jsonl` are the variants.

## Query understanding (stage 7): built, measured, left off

- **What:** `src/query.py` (one structured-output LLM call: products, 1-3 queries, hypothetical answer; cached on disk by question + provider + model + prompt)
  and `search_plan()` in `src/search.py` (original question + rewritten queries + product-routed searches + HyDE dense list, merged with RRF). The original
  question is always searched, so a bad plan only adds candidates. A product the caller chose explicitly is never widened by the plan. Access rules apply
  inside every search; a test runs all plan modes as public and as a one-product member and checks nothing unreadable comes back.
- **The question is data:** it goes in the user message only, never in the system prompt (tested).
- **Chose: do not enable it** (`query.use: []`). Measured against plain search on the tuning split: answer-in-context 0.56-0.65 vs 0.635, no consistent gain
  (see README, Query understanding). *Why keep the code:* routing is accurate with Groq (26 of 26), HyDE raised passage recall@10 by 4 items, and it is the
  basis for the retry loop (stage 16). *Considered:* enabling HyDE only (best recall, worse MRR, +1 item in context: not convincing).
- **LLM client now has a provider order** (`llm.prefer`, per-call `prefer=`), as you allowed Groq for the generator and the query rewriter. Default stays
  `local` first; the other provider is still the failsafe and every fallback is logged. Groq's `gpt-oss-120b` is a reasoning model: its hidden thinking tokens
  count against `max_tokens`, so a 200-token cap failed with `json_validate_failed`; Groq calls now use `llm.groq.max_tokens: 1500` and `reasoning_effort: low`,
  and retry up to 3 times on rate limits. (This also makes the Groq fallback for answers more reliable than before.) CLAUDE.md still says local is the default;
  I did not edit it, update it if you want Groq first.
- **Finding that changes the plan:** the passage-level label is one sentence, so "answer in context" counts a miss when a different chunk of the same page answers
  the question (inspected for `sym-02` and `x-05`). The real retrieval accuracy is somewhere between 0.64 (strict) and 0.90 (page recall@10). Further retrieval
  work is being optimised against a pessimistic proxy until there is a correctness judge (question + retrieved context + reference evidence -> is the answer
  derivable?), and a bigger question set. That is the next step.


## Phase 1 of `docs/IMPROVEMENT_PLAN.md`: measure real answer accuracy (2026-10-20)

Goal: a number for the user's metric, accuracy = (answerable answered **correctly** + unanswerable **refused**) / all, before changing the pipeline.

- **Accuracy needs a judge, and the judge is another model family.** `eval/judge.py` uses Groq `qwen/qwen3.8-27b` (D2; the answer writer is Qwen2.5-3B locally, gpt-oss-120b later).
  It sees the question, the reference key points, the labelled evidence quotes and the answer text, and returns per-point flags, a verdict, missing points and wrong claims.
  *Considered:* the NLI model (it measures "supported by the cited text", not "right"; circular with the verifier), a judge on the answer writer's own model.
- **The verdict is derived in code from the per-point flags.** In the first smoke test the judge wrote "satisfies the at-least-one-of requirement" and still returned `partially_correct`.
  Now the model commits to `points_stated` (one true/false per key point) and code decides: any wrong claim -> incorrect; all essential points stated -> correct; some -> partially_correct; none -> incorrect.
  Refusals need no LLM call (refused answerable = not correct, refused unanswerable = correct, answered unanswerable = incorrect). Partial counts as not correct and is reported separately.
- **Judge validated against my labels (prompt v2):** 30 baseline answers (17 correct, 5 partial, 8 incorrect), labelled by me from the answer, key points and source text *before* seeing the judge's verdicts.
  Agreement on correct vs not correct **29/30 = 96.7%** (95% CI 83.3-99.4%), exact verdict 27/30 = 90.0% (`eval/results/judge_validation.md`; labels in `eval/judge_labels.jsonl`).
  The one disagreement (`err-21`): the answer hard-codes `git checkout master`, the key point wrote `${GITHUB_REF:11}`; the judge was stricter than me. I did not change prompt or key point afterwards.
  *Limit (D4):* one LLM judging against another LLM's labels overstates reliability; **please spot-check about 10 of the 30** (`eval/judge_labels.jsonl` has the answer and my note for each).
- **I verified the questions (D4), not a human.** 104 questions now: the original 40 plus 50 answerable and 14 unanswerable new ones; every new question and every tune key point carries `verified_by: "assistant"` and a `verify_note`.
  What that meant in practice: of 74 LLM-drafted answerable questions (gpt-oss-20b), 38 were kept, 17 dropped, 19 never reviewed (surplus); **every kept one was edited** (37 of 38 got a rewritten question; 4 were re-typed
  because the draft invented an "error message"). None of the 26 key-point drafts for the existing tune questions (Qwen 27B) survived unchanged; typical fixes: key points taken from the question instead of the accepted answer,
  alternatives merged into one "at least one of" point, a missing second product half in cross-product questions. 14 of 14 drafted unanswerable questions were reworded to be about the tool itself, because several
  (a Rancher image-pull error, a Jenkins "Repository not found") have generic answers in the corpus; `absent_terms` are enforced by a test over the whole corpus. 10 cross-product and 2 version questions were written by me from corpus passages, because the LLM pairs were contrived.
- **Key points** are `{text, essential}`; "at least one of" is how alternatives are written (the judge prompt says one is enough). Cross-product questions have one essential point per product.
  `acceptable_pages` lists extra pages that contain a valid answer; two were added **after** seeing the baseline (`ver-07`: `upgrade.md`, `x-06`: the `oidc-in-*.md` how-tos). That changes the failure classification only, not the accuracy.
- **Split and dev subset.** Tune 70, holdout 34 (new questions assigned about 63/37 to each, before anything ran on them). A fixed 40-question dev subset of tune (`"dev": true`, spread over the five types) is for day-to-day runs.
  **The 10 original holdout questions were not touched** (the instruction was to touch holdout only to add questions): 8 answerable ones still have no `key_points`; they get them right before the final run in Phase 5 (a test lists them).
- **The LLM client got three things the eval needs** (`src/llm.py`): a disk cache for every call (`cache="name"`, key = provider + model + messages + settings, appended per call so a stopped run loses nothing),
  per-model pacing for the Groq free tier (30 req/min, 8,000 tokens/min, from the `x-ratelimit-remaining-tokens` header and a local window; 429s are waited out), and a clean stop when a daily limit is hit
  (`QuotaExhausted`; the eval prints how many questions it finished and the same command resumes from the cache). Each stage uses its own model (= its own free-tier bucket): drafting questions on gpt-oss-20b, key-point drafts and the judge on qwen3.8-27b, answers (Phase 2) on gpt-oss-120b.
  Judge and drafting calls never fall back to the local model (`fallback=False`). Daily tokens are read from `data/cache/groq_usage.jsonl` (rolling 24 h); the server's 429 stays the authority.
  Model names checked with `GET /openai/v1/models` on 2026-10-20: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` all exist; qwen emits no thinking text by default and supports strict JSON schema.
- **CLAUDE.md "Limits" is not edited yet.** D1 (Groq as default answer writer) takes effect in Phase 2a; the line changes then. Using Groq for the judge and for drafting questions is the plan's D2/D4, public docs and test questions only.
- **Baseline = the current pipeline, unchanged** (local Qwen2.5-3B, bge-small, hybrid, 5 chunks / 8,000 characters, NLI verifier at 0.3): `python -m eval.accuracy --name baseline` on the full tune split.
  Result: **21/70 = 30.0% (95% CI 20.5-41.5%)**, 40.0% with the verifier off (`eval/results/accuracy_baseline_tune.md`). That is below the plan's guess of 45-55%, which counted every non-refused answer as correct;
  only 12 of the 26 answers that were shown were correct. The judge was checked first (agreement above), so the gap is real, not a judge artefact.
  Failure breakdown (49 not correct): retrieval_miss 12, generation_error 18, verifier_false_refusal 15, unsafe_or_wrong_claim 4. Cross-product: 0 of 11 correct.
  The model fell back to Groq 4 times of 70 (unusable local output); those 4 calls are in the token table.
- **Run-to-run spread (guardrail: run every variant twice).** The same baseline with the answer step sampled again (`--salt run2`) scored **26/70 = 37.1%** (95% CI 26.8-48.9%) against 30.0% in the first run:
  5 questions, 7.1 points, 63 of 70 questions with the same outcome (`eval/results/spread_baseline_vs_baseline_run2.md`). The local model samples at temperature 0.1 and the answers are cached, so a plain rerun is identical;
  `--salt` is the way to repeat for real. From now on a change counts only if it clears this spread, and both runs are the reference, not the better one.
- **Tokens used in Phase 1** (Groq from `data/cache/groq_usage.jsonl`, rolling 24 h, no quota stop happened; local from the result files):
  `gpt-oss-120b` 11,309 (5 answer calls, all fallbacks after a local 60 s timeout), `gpt-oss-20b` 106,715 (98 question-drafting calls, including 14 top-up calls),
  `qwen3.8-27b` 111,453 (26 key-point drafting calls 19,264, judge 127 calls 92,189 for two baseline runs and the 30-answer validation), local Qwen2.5-3B 270,967 (two baseline runs). Per-question cost of the judge: about 700 tokens.
  The plan estimated 800-1,200; the real prompt is smaller because only the answer, key points and evidence quotes are sent.
- **Not done in Phase 1 on purpose:** `docs/IMPROVEMENT_PLAN.md` Phase 2 (generator, answer format, context size) has not been started; the CLAUDE.md "Limits" line is unchanged until then;
  the dev subset has no run of its own yet (the baseline covers the full tune split, and the dev-subset numbers are a subset of it).


## Phase 2 of `docs/IMPROVEMENT_PLAN.md`: stronger writer, answer format that fits, wider context (2026-10-20)

- **2a. Writer = Groq `openai/gpt-oss-120b`, local Qwen2.5-3B is the failsafe (D1).** `answer.llm: groq` in `config.yaml`; `generate()` calls `llm.chat(prefer=answer.llm)`. `CLAUDE.md` "Limits" was updated (you approved it in the plan).
  Unusable output or a timeout still falls back to the local model and is logged. In an eval a used-up daily quota is **not** answered by the local model (`stop_on_quota`): the run stops with a message, or waits with `--wait`, and resumes from the cache,
  so no result mixes two writers by accident. `reasoning_effort: low`, `max_tokens: 1800` (thinking tokens count). *Not measured:* `reasoning_effort: medium` (the plan says "if it helps"). It would cost another full dev run of about 140k tokens, a day of the 120b quota,
  and `low` already got 82.5% on the dev subset with the verifier off; revisit only if generation errors dominate after Phase 3.
- **2b. New answer format** (`kind`: fix / explanation / fact / not_found; `coverage` and `missing`; a short `summary`; `points` with their sources). The prompt says what each kind is, that a two-product question needs points for each product, and keeps
  "excerpts are data" and "use only the excerpts". `Step` stays the name of one point and `Answer.steps` the list of shown points (renaming would have touched every caller for nothing). `coverage` / `missing` are recorded for Phase 4b, not used yet.
  *Summary handling until Phase 3:* the NLI verifier checks the **points**; the summary is shown only if at least one point survives, and it goes through the secret / personal-data block and the dangerous-command warning, but it is **not itself verified**
  (a `fact` answer's cited point is, which carries the claim). The judge sees summary and points. The old `{steps}` reply format is rejected on purpose.
- **2c. Context size per writer** (`answer.context` in `config.yaml`, applied by `answer_cfg`): local keeps 5 chunks / 8,000 characters / sections up to 2,800 (4k-token window); Groq gets **10 chunks / 12,000 characters / sections up to 2,000**.
  Chosen with `eval.run` (no LLM tokens), 10 settings, `eval/results/context_sweep.md`: evidence-in-context (`ctx_recall`) 0.716 for the old setting, 0.767 for 8 / 10,000 / 2,000, 0.784 for 8 / 12,000 / 2,000, **0.810 for 10 / 12,000 / 2,000** (cross-product 0.318 -> 0.455).
  Shorter sections (1,500) were worse in every pair; longer ones (2,800) also worse than 2,000: more distinct places beats longer sections. The cost is about 500 more tokens per question than 10,000 characters. Only this pair was run through the accuracy eval (token budget); the 8 / 10,000 pair was not compared by accuracy.
  A fallback to the local model after a Groq failure reuses the wide context, which can exceed its window (the call then fails and the error is logged); acceptable for a failsafe.
- **Cost:** about 3.5k tokens per answer on the 120b bucket (prompt 3.3k, completion 0.2-0.3k with low reasoning): 141k for the 40-question dev run, so the full 70-question tune split does not fit in one 200k/day window.
  The full tune run (`python -m eval.accuracy --name p2 --wait`) was started right after the dev run and waits for the rolling window; whatever finished is cached.
- **Result on the dev subset (40 questions, the same questions the baseline had):** **45.0%** (18/40, CI 30.7-60.2%) with the old NLI verifier, **82.5%** (33/40, CI 68.0-91.3%) with the verifier off, against 27.5% and 42.5% for the baseline run on those questions
  (`eval/results/accuracy_p2_dev_tune.md`, `spread_baseline_vs_p2_dev_dev.md`). Draft correct went from 17 to 33 of 40. With the verifier on, 15 of 22 misses are `verifier_false_refusal`: the NLI verifier, built for a 3B model's invented steps, now refuses
  21 of 33 answerable questions whose drafts are mostly right (it still refuses all 7 unanswerable ones, and the writer itself refused all 7 with the verifier off). That is the Phase 3 job. Wrong or dangerous claims in shown answers: 0.
  The writer's own `coverage` flag is informative: when it says `full` the draft is correct 24 of 28 times.
- **What 82.5% does and does not say.** It is the draft before any verification, on 40 questions (CI +-14 points), judged by a model that agreed with my labels on 29 of 30 baseline answers; the new answers are longer and more varied than that sample, so the judge validation should be repeated on a few of them
  (not done). Cross-product is still the weak type (2 of 6 with the verifier off).


## Phase 3 of `docs/IMPROVEMENT_PLAN.md`: LLM claim check instead of the NLI verifier (2026-10-20)

- **What we chose.** One cached Groq `gpt-oss-20b` call per answer (`verify.method: llm`, `src/verify.py` `claim_check`; its own token bucket, temperature 0, `reasoning_effort: low`, no switch to another model). Input: question, summary, points, and only the excerpts the points cite. Output: a status per point and for the summary
  (supported / partially_supported / unsupported) and `answers_the_question` (yes / partly / no). *Why:* the NLI model scored commands, code and list items near 0 and saw each step without the question; it refused 15 of 40 good drafts of the 120b writer. *Considered:* tuning the NLI threshold (it was tuned for the 3B model, and the problem is the model, not the number);
  running the check on the 120b bucket (the answers already use it).
- **Policy.** The citation check (ids exist, caller may read them) stays first and needs no LLM; a point without a valid citation is unsupported without asking. Unsupported points and an unsupported summary are dropped. **`partially_supported` points are kept** (the plan said "drop unsupported"; the partial ones are mostly a correct point with an extra detail, and dropping them would repeat the false-refusal problem).
  Refuse if no point is left or `answers_the_question` is `no`; `partly` is shown with the note `verify.partial_note`. A refused answer keeps its per-point results in `Answer.checked` for the eval's failure breakdown.
- **Fallback.** If the claim check fails (down, timeout, unusable output, quota) the old NLI scorer checks that answer, the fallback is logged (`FALLBACK claim check -> nli`) and `Answer.verified_by` says `nli`. In an eval a used-up daily quota is not answered by NLI (`stop_on_quota`): the run stops and resumes from the cache, as for the writer.
  `min_supported_fraction` is **not removed** (the plan said to): the fallback still uses it; the LLM path does not. `eval/answer.py` is forced to `method: nli` because it measures the NLI verifier.
- **Result on the dev subset (40 questions, the same cached 120b answers as Phase 2):** accuracy **82.5%** (33/40, CI 68.0-91.3%) with the claim check on, against 45.0% with the NLI verifier and 82.5% with the verifier off. `verifier_false_refusal` 15 -> 0; 7 of 7 unanswerable refused; failures 2 retrieval_miss, 3 generation_error, 2 unsafe_or_wrong_claim
  (`eval/results/accuracy_p3_dev_tune.md`, `spread_p2_dev_vs_p3_dev_dev.md`). The plan's acceptance (false refusals near 0, unanswerable still 100%) is met.
- **What it does not show.** The check changed 3 of 40 answers and no outcome: of 95 checked claims 87 supported, 5 partial, 3 unsupported, no `partly`, no `no` on a shown answer. It did not stop the 3 answers the judge calls wrong. And since the writer refused all 7 unanswerable questions itself, the `answers_the_question: no` rule was never needed; it is untested on a writer that answers an unanswerable question.
  40 questions give +-14 points.
- **Cost:** 32 checks, 53.6k tokens on the 20b bucket (about 1.7k each, below the plan's 2-2.5k); 2.1k new judge tokens (most shown answers equal the draft, so the judge cache was reused). Not run: the other 30 tune questions (120b quota; the `p2` run in the memory TODO) and the judge validation on longer answers.
- **Next:** Phase 4 (bge-m3, retry on `coverage`, chunk prefix) on the remaining retrieval and cross-product misses.


## Phase 4 of `docs/IMPROVEMENT_PLAN.md`: retrieval for the remaining misses (started 2026-10-20)

All three Groq buckets (120b, 20b, qwen) were used up for the rest of the day by Phases 2-3, so Phase 4 has **no accuracy measurement yet**. What was done without LLM tokens:

- **4a. bge-m3 as default embedding (D3): rejected for now.** Measured with `eval.run` on all 58 answerable tune questions at the Phase 2 context (10 chunks / 12,000 / 2,000, hybrid, collection `exp_fixed500_m3`, `eval/results/p4a_m3_ctx_tune.md`):
  evidence-in-context (`ctx_recall`) **0.767 against 0.810** for bge-small; page recall@10 0.931 against 0.940; MRR 0.905 against 0.890; median search 210 ms against 79 ms (question embedding on CPU). Cross-product is the one type where it is ahead (evidence-in-context 0.500 against 0.455, 11 questions). Its earlier gain (0.635 -> 0.712) was at the old 5-chunk / 8,000-character context; with ten chunks bge-small already catches up, and the wider context hides the difference.
  The plan says to judge by accuracy; it was not run because a 120b run costs a day of quota and the retrieval measure that predicts accuracy (does the context hold the evidence) went down, not up. `config.yaml` stays on bge-small; CLAUDE.md's embedding line is unchanged. *Revisit* only if retrieval is still the largest failure bucket after the retry is measured.
- **4c. Contextual prefix (cheap version): built, measured, not adopted.** `python -m src.index --prefix --collection exp_prefix500_small --recreate` embeds `title > heading > subheading` + the chunk text (heading path found by locating the chunk in its page, `src/context.py` `heading_path`) and stores it as payload `context`; BM25 reads it too; the shown text is unchanged. Indexing took 403 s on CPU.
  Result (same setting, `eval/results/p4c_prefix_ctx_tune.md`): `ctx_recall` **0.810, the same as without**; passage recall@10 0.845 against 0.810; but MRR 0.842 against 0.890 and page recall@10 0.931 against 0.940; cross-product recall@10 0.636 against 0.682. Mixed and nothing where it decides answerability, so no re-index of `support_docs`. The option stays (tested) for later.
- **4b. Retry loop (stage 16): measured, no gain, switched off (`retry.enabled: false`).** Built as: the writer's `coverage` is partial or none -> query plan on `gpt-oss-20b` (`understand()` got `model` and `stop_on_quota`), the writer's `missing` text as one more query, `search_plan(rewrite+route+hyde)`, RRF with the first hits, 12 chunks / 14,000 characters, one more answer; a refusal on retry keeps the first draft.
  **Result on the dev subset** (`python -m eval.accuracy --name p4b_dev --dev`, `eval/results/accuracy_p4b_dev_tune.md`, `spread_p3_dev_vs_p4b_dev_dev.md`): **80.0%** (32/40, CI 65.2-89.5%) against **82.5%** without the retry (`p3_dev`). It ran for 12 questions (5 answerable, 7 unanswerable): the 7 unanswerable stayed refused (7 of 7), so the feared leak did not happen.
  Of the 5 answerable: `x-09` improved (partly correct -> correct, coverage partial -> full), `x-08` got worse (correct -> partly correct), `x-12` got worse (correct -> incorrect, although coverage rose to full), `x-06` went from a refusal to an incorrect answer, `x-02` unchanged (retrieval still misses). Net 1 better, 2 worse, 1 changed wrong-for-refused; the gap is inside the noise (1 question = 2.5 points), but there is no gain to pay for.
  Cost: 45.9k tokens on the 120b bucket, 16.1k on 20b (the plan calls and a claim check per retried question). *Why it did not help (a reading, not tested):* a wider mixed context gave the writer more to blend; 2 of the 5 answerable misses are retrieval (`x-02`) or a refusal the writer already made correctly. The code stays, off by default (tested with fakes). Not tried: retry with the first context kept intact plus only the new hits appended.
- **Phase 4 closes with no change to the pipeline's defaults.** Dev accuracy stays 82.5% (Phase 3 numbers); the remaining misses are cross-product questions and retrieval, which the three cheap levers above did not move.


## Phase 5 of `docs/IMPROVEMENT_PLAN.md`: final measurement on the holdout (2026-10-22)

- **Before the run (you asked for more questions):** added `key_points` to the 8 original holdout answerable questions (written from their source text and checked by the assistant, D4), marked `none-01` / `none-06` verified, and added 4 **near-miss unanswerable** holdout questions
  (a believable but non-existent setting in a covered product: `max_vacuum_workers`, `spec.podRestartBackoffSeconds`, `log.retention.compaction.ratio`, the `retry-on-failure` job key; each term is absent from the corpus). Holdout 34 -> 38 questions. None of these were run before the final run, so nothing was tuned on them. Adding questions measures the app better; it does not change it.
  The question tests were updated (the "holdout untouched" rule was lifted on purpose).
- **Config frozen:** `answer.llm: groq` (`gpt-oss-120b`, effort low), bge-small hybrid, 10 / 12,000 / 2,000, `verify.method: llm` (`gpt-oss-20b`), `retry.enabled: false`. Run once: `python -m eval.accuracy --final --name final`.
- **Result: 78.9%** (30/38, CI 63.7-88.9%; `eval/results/accuracy_final_holdout.md`). 18 of 26 answerable correct, 3 partial, 4 incorrect, 1 refused; 12 of 12 unanswerable refused. By type: error 7/8, symptom 5/7, version 6/6, **cross-product 0/5**, unanswerable 12/12.
  Failures: 3 retrieval_miss, 3 generation_error, 2 unsafe_or_wrong_claim, 0 verifier_false_refusal. The 4 answers with `coverage: partial` were all wrong. Cost: 133k tokens on the 120b bucket, 43k on 20b, 19k new on qwen.
- **Against the 80%+ target:** the point estimate is just under it and the interval spans 64-89%, so the honest statement is "about 80%, not distinguishable from 75% or 85% on 38 questions". The plan's 90% was not reached.
- **Nothing tuned after seeing it.** Next steps if work continues: cross-product (two-part questions) is the clear gap; the retry loop did not fix it on the dev subset; a bigger test set and a second writer (see the NVIDIA check) are the cheapest ways to learn more.


## Entry side and finish (stage 7, UI, README) (2026-10-22)

- **Login: salted scrypt + HS256 JWT, three demo users.** `python -m scripts.setup_users` generates the passwords with `secrets`, prints them once and stores only hashes (`credentials` table in `data/access.db`); `JWT_SECRET` is created in `.env`. Chosen over: a login library or an OAuth server (too much for a demo; keep it simple),
  and over storing the role in the token (reading it from the database each request makes a revoked license or deleted user effective at once, at the cost of one SQLite read). `PyJWT` was added (`uv add pyjwt`; this also swapped the venv's torch from the CUDA build to the CPU build the project already targets: everything runs on CPU).
  No token = public role; an invalid token = 401, never a silent downgrade. A 5-failure lockout per user name is in memory. Demo users: alice (member: kubernetes, postgres), bob (member, no licenses), admin.
- **Input safety = named regex rules, not a model.** Why: free, instant, explainable (the rule that fired is logged), no tokens (the quota is the binding constraint). Considered: an LLM classifier (costs a call per question and can itself be prompt-injected) and a small local classifier (more setup than the project's day allows). The text is normalised first (NFKC, zero-width characters, letters spaced out one by one).
  **Result** (`eval/results/input_safety_first_run.md` vs `input_safety.md`): first run **14 of 20 attacks blocked, 3 of 20 normal questions wrongly blocked** (`disable authentication` for a Kafka broker, `developer mode` for PostgreSQL, a pasted log line starting `system:`); I then fixed the rules for those six misses and three false blocks on the same prompts and reached 20 of 20 and 0 of 20.
  That second number is **tuned on its own test set** (and I wrote both the rules and the prompts), so it overstates how the guard does against a stranger; the first run is the better estimate. Known limits: paraphrases, languages beyond a few cognates, and any 80+ character unbroken string looks like an encoded payload.
- **Injection inside a retrieved chunk: two layers, both tested.** (1) `scan_chunk` leaves a chunk out of the context when it looks like injected instructions (narrower rules than for questions, because docs use "ignore" and "override" legitimately; the first version flagged 8 of 2,602 real chunks, the tightened one flags 0).
  4 poisoned test chunks are all caught. (2) With the scanner off, the real writer (Groq 120b) was given a real context plus a poisoned chunk (`--live`, 2 cases): it obeyed neither (one answered normally, one refused). That is 2 samples, not a guarantee. Retrieved text stays "data, never instructions" in the writer prompt.
- **Rewrite = one cached `gpt-oss-20b` call, only with a history; product detection reuses the query plan.** Considered: always rewriting (a wasted call for first questions) and routing the search to the detected product. **Product routing stays off** (`rewrite.route_product: false`): the detected product is shown, but a wrong single guess would hide the right docs and its effect on accuracy was not measured (no tokens left to do it). The follow-up rewrite is tested only with a fake LLM; no multi-turn test set exists.
- **HyDE (optional item): not redone.** It was built and compared on the tuning questions earlier (`docs/RESULTS.md`, Query understanding): it raised passage recall@10 slightly but not the context evidence or MRR, so it stays behind `query.use` (off). I did not spend tokens repeating that.
- **Not in the accuracy numbers.** The accuracy evals call search -> context -> generate -> claim check directly, so login, the input guard, the rewrite and the chunk scan are not part of the 78.9%. The chunk scan flags 0 of the 2,602 real chunks, so it cannot change which chunks the eval sees; the rewrite makes no call without a history, so a single-turn question is unchanged.
- **UI = Gradio mounted on the FastAPI app (`python -m src.ui`), calling the same functions as the API in-process.** *Superseded 2026-10-23 by the Next.js app, see "Web app" below; `src/ui.py` and the `gradio` dependency were removed.* Considered: a separate UI process that calls the API over HTTP (two processes to start; more moving parts for a one-person demo). Answers show citations as links to the source pages, the retrieved passages in an accordion, and a banner for "No documented fix found". Text from the model or the docs is rendered with images and links removed
  (so a poisoned passage cannot make the page fetch a URL) and passages are shown in code blocks. Checked by render tests and an HTTP smoke test (login, a blocked injection, one real answer with sources and 6 passages, 401 for a junk token), **not by a person using the page.**
- **README rewritten as the final summary; the long experiment log moved unchanged to `docs/RESULTS.md`.** All results tables in the README are generated from `eval/results/*.json/.md` (not typed by hand).
- **"Run the final setup once on the 10 untouched test questions": already done.** The 10 original holdout questions were part of the single holdout run (38 questions), so rerunning would spend about 130k tokens for the same result. `python -m eval.final_ten` extracts them from that run: **9 of 10 correct** (the miss is `x-03`, a cross-product question, partly correct; both unanswerable ones refused).
  The 28 other holdout questions were added by me before the run (D4: verified by the assistant, not a human).

## Web app: Next.js UI, MongoDB users, admin licenses (2026-10-23)

- **Frontend: Next.js (React, TypeScript) in `web/`, replacing Gradio.** Why: Gradio could not give a custom sign-in page, an admin console, a live evaluation screen or the evidence strip without fighting its layout. *Considered:* Streamlit (same limits, reruns the whole script on every click), keeping Gradio (the cost of the change was the point of the request). Cost: two processes to start (API + web) and a Node toolchain. Plain CSS tokens, no Tailwind or component library. Look: the `achromatic-ledger` style of the design-taste-frontend skill (no colour in the chrome, one blue only on the main data: cited passages, correct answers, the pipeline row), Geist, an icon rail, no gradients or glass. Layout and states checked at 1440 / 768 / 390 px with the skill's inspector (`--app`).
- **Users move to MongoDB 7 in Docker (`docker-compose.yml`, named volume, bound to 127.0.0.1, root password `MONGO_PASSWORD` from `.env`).** *Considered:* keeping SQLite (worked, but the request asked for MongoDB), a managed cloud database (not free/local). `AccessStore` keeps the same method names; collections `users` (with the hash), `licenses`, `audit`. Tests use `mongomock`; nothing needs Docker except the real run. The old `data/access.db` is left untouched and unused; `setup_users` recreated the demo users with new passwords.
- **Passwords: peppered scrypt, not encryption.** "Encrypted everywhere" is done with a one-way hash, because anything that can be decrypted can be stolen with the key. Each password goes through HMAC-SHA256 with `PASSWORD_PEPPER` (in `.env`, not in the database), then salted scrypt (n=2^14). A stolen database alone cannot be attacked offline. The plain password exists only in the login request and, for an admin-created user, in the admin's browser until it is handed over; the API requires 10+ characters. Not done: encryption at rest for MongoDB (not in the community edition), HTTPS (localhost).
- **JWT yes, OAuth2 no.** The API issues an HS256 bearer JWT after a password check; that is not an OAuth2 flow (no authorization server, scopes or refresh tokens). Kept simple on purpose. *Considered:* a library such as Authlib or an identity provider (too much for the project).
- **The token never reaches page scripts.** Next.js route handlers (`app/api/session`, `app/api/backend/[...path]`) keep the JWT in an `httpOnly`, `SameSite=Lax` cookie and add the `Authorization` header when calling FastAPI; the browser only talks to Next.js. Mutating routes need a custom header and a same-host `Origin` (CSRF); the proxy allows only `ask, documents, metrics, me, admin`. An expired token clears the cookie and returns to the sign-in page. (A first version compared `Origin` with the URL Next.js believed it had, which refused `127.0.0.1`; it now compares with the `Host` header.)
- **Admin: create users and switch licenses.** Endpoints under `/admin/*` check the role on every call; every change is in the audit log shown on the page. No delete-user and no role change in the API (deleting data needs a separate decision); a member cannot grant themselves anything (tested). Switches update at once and roll back with a message if the server refuses.
- **Model text stays data.** `web/lib/richtext.ts` renders answers and passages as text, inline code and code blocks only: no links, images or HTML from the model or the docs (the same guarantee the Gradio page had), documentation links only if plain `https`. Tested with `npm test`. HTML entities left in some imported titles (`&quot;`) are decoded for display; the ingest data is not changed.
- **Evaluation screen reads `eval/results/*.json` through `/metrics`.** Nothing is typed into the UI; the page's headline sentence (the weakest question type) is computed from the data. It repeats the README's caveats (38 questions, assistant-written questions, safety rules tuned on their own prompts).
- **One start command: `launch.cmd` -> `scripts/start.py` (stdlib + project code, no new dependency).** It checks, then starts, in dependency order, and prints an `ok / warn / FAIL` line per part with waits shown as elapsed seconds (Qdrant needs about 1.5 minutes after a start). Reuses anything already running instead of starting it twice. Required parts fail the start; LM Studio (only the failsafe writer) and the Groq key warn. LM Studio output goes to a log file because `lms load` prints a spinner thousands of lines long. Considered: `docker compose` profiles only (cannot start LM Studio or the API), a PowerShell script (the checks are easier to write and test in Python). Named `launch.cmd`, not `start.cmd`, because `start` is a built-in `cmd` command. Passwords stay unrecoverable on purpose; `setup_users --reset --user NAME` issues a new one. The local-models check asks whether `config.json` is in the Hugging Face cache, not whether the snapshot is complete, because `download_models` deliberately skips the ONNX files.
- **Motion** follows the Emil Kowalski `animate` skill (installed with `npx skills add emilkowalski/skills`, three skills: animate, animation-performance, review-animations). Used for meaning only: the evidence strip draws in rank order and cited passages are tall and blue; a wave of ticks shows "working" (not progress); the citation chip, source row, strip tick and passage highlight together on hover; passages open with a short height transition; bars on the Evaluation and sign-in screens draw once when they scroll into view; switches, new rows and menus use 150-220 ms ease-out. Only `transform`, `opacity`, `clip-path` (plus the one accordion height); hover gated to real pointers; `prefers-reduced-motion` drops the travel. Nothing animates on keyboard actions (sending a question).
