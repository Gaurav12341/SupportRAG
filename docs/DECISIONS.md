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
