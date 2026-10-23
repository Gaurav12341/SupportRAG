# RESULTS: the full experiment log

Moved here from the README when the project was finished. Newest results and the summary are in `README.md`; reasons for every choice are in `docs/DECISIONS.md`. Commands used for the experiments:

## Experiment commands

Built: stages 1-6 (ingest, embed, store), 8-11 (search), 12-14 (answer with citations, verifier, output safety) and the
evals (retrieval, answer support, and end-to-end answer **accuracy** with a correctness judge). Question rewriting / product routing / HyDE (7) is built but off (no proven gain). Not built yet: login and input safety (7), UI and API, agentic retry (16).
Accuracy: baseline 30% (local writer), 45% after Phase 2 on the dev subset (82.5% with the verifier off, which Phase 3 fixes); see Results. `docs/IMPROVEMENT_PLAN.md` is the plan.

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
.venv\Scripts\python -m src.answer "pod stuck in CrashLoopBackOff" --role member --licenses kubernetes
.venv\Scripts\python -m eval.answer --name answer_v7    # verifier off vs on, tuning split (support only, no correctness)
.venv\Scripts\python -m eval.accuracy --name baseline  # end-to-end accuracy on the tuning split (judge = Groq qwen3.8-27b; resumable, cached)
.venv\Scripts\python -m eval.judge --validate          # judge vs my 30 labels (eval/judge_labels.jsonl)
.venv\Scripts\python -m src.ingest --strategy recursive --size 250 --out chunks_x.jsonl   # chunking experiment, leaves chunks.jsonl alone
.venv\Scripts\python -m src.index --chunks chunks_x.jsonl --collection exp_x --embedding BAAI/bge-m3 --device cuda --recreate
.venv\Scripts\python -m eval.run --name x --mode hybrid --collection exp_x --embedding BAAI/bge-m3   # page + passage metrics
.venv\Scripts\python -m pytest                          # about 16 minutes with Qdrant running (loads the models, searches the real index)
```

Copy `.env.example` to `.env` and set `GROQ_API_KEY` (the default answer writer `gpt-oss-120b`, the judge and question drafting of the accuracy eval; only public docs and test questions are sent).
Start the LM Studio server and load `qwen2.5-3b-instruct` (the failsafe writer).
`make up | ingest | index | eval | ui` (`make` is not installed on this machine yet).


## Results

Retrieval, one change at a time. Tuning split, 26 answerable questions (the original set; the tuning split now has 58, so rerunning `eval.run` gives different numbers), top 10 chunks searched. Every number is
copied from `eval/results/*.json` by `python -m eval.table` (saved as `eval/results/retrieval_steps.md`); per-question
before/after lists are in `eval/results/compare_*.md` (`python -m eval.compare <before> <after>`).
Roles are **simulated** (the docs are public; levels come from `configs/access_rules.yaml`). Rows 0-3 and 4a use role admin
(no restriction), so they are comparable; "Kept = no" means the default config does not use it.

| Step | Kept | Recall@5 | Recall@10 | MRR | MRR error_message | MRR symptom | MRR version | MRR cross_product | Median ms |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 0. Baseline: dense only, fixed 500-token chunks | - | 0.904 | 0.904 | 0.763 | 0.905 | 0.760 | 0.622 | 0.740 | 124 |
| 1. Heading-aware chunks, dense only | no | 0.808 | 0.865 | 0.753 | 0.857 | 0.733 | 0.854 | 0.515 | 128 |
| 2. Fixed chunks + BM25 merged with RRF (hybrid) | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 125 |
| 3. Hybrid + cross-encoder rerank (top 30, keep best 5) | no | 0.904 | 0.904 | 0.822 | 0.929 | 0.792 | 0.722 | 0.840 | 3197 |
| 4a. Hybrid, admin (all levels, all products) | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 122 |
| 4b. Hybrid, member licensed for all 4 products | yes | 0.865 | 0.904 | 0.825 | 0.905 | 0.838 | 0.653 | 0.900 | 124 |
| 4c. Hybrid, member licensed for github only | yes | 0.673 | 0.712 | 0.644 | 0.762 | 0.594 | 0.403 | 0.850 | 127 |
| 4d. Hybrid, public (not logged in) | yes | 0.654 | 0.692 | 0.635 | 0.762 | 0.594 | 0.403 | 0.800 | 126 |
| Re-test: heading chunks + hybrid (admin) | - | 0.846 | 0.885 | 0.770 | 0.857 | 0.854 | 0.640 | 0.667 | n/a |
| Re-test: heading chunks + hybrid + rerank (admin) | - | 0.865 | 0.904 | 0.855 | 1.000 | 0.875 | 0.663 | 0.850 | n/a |

"Median ms" is one search on CPU after warm-up. The two re-test rows were scored once on a saved copy of the
heading-chunk index; no latency was taken for them.

What each change did, by question type (change in MRR unless noted):

| Change | error_message | symptom | version | cross_product | Questions helped / hurt |
|---|--:|--:|--:|--:|--:|
| 1. Heading chunks (vs 0) | -0.048 | -0.027 | +0.232 | -0.225 | 5 / 8 |
| 2. + BM25 and RRF (vs 0) | +0.000 | +0.077 | +0.031 | +0.160 | 7 / 4 |
| 3. + rerank (vs 2) | +0.024 | -0.046 | +0.069 | -0.060 | 7 / 5 |
| 4. public instead of admin | -0.143 | -0.244 | -0.250 | -0.100 | 2 / 6 |

Reading it (n is small: one question moves Recall by 4-20 points, so treat differences under about 0.05 as noise):

- **1. Heading chunks: not kept.** Recall@5 fell 0.904 -> 0.808 and MRR was flat (0.763 -> 0.753). It helped version
  questions but lost `err-09` (an exact error message) and hurt cross-product questions. Chunks are better formed
  (none cut a code block or table) but there are 47% more of them (3816 vs 2602), and several chunks of one page crowd the top 10.
  Re-tested with the later stages (last two rows): with hybrid it is still worse than fixed chunks
  (MRR 0.770 vs 0.825); with rerank its MRR is higher (0.855 vs 0.822) but Recall@5 is lower (0.865 vs 0.904). No clear win on 26 questions, so it stays off.
- **2. BM25 + RRF: kept.** MRR 0.763 -> 0.825 with Recall@10 unchanged; Recall@5 dropped by one question (a version
  question moved from rank 5 to 6). Questions it helped contain distinctive literal words (`Terminating`, `evicted`,
  `kafka-streams-scala`, `runs.using`, `kubeconfig`) and the two-product questions. **It did not help exact error
  messages** (MRR 0.905 before and after): dense search already found those.
- **3. Reranker: not kept by default.** MRR 0.825 -> 0.822 and Recall@5 +0.038 (one question), for about 3.2 s more
  per search on CPU (3197 ms vs 125 ms). It moved some questions up (version, error_message) and others down (symptom, cross-product).
  Turn it on with `retrieval.mode: rerank` in `config.yaml`; worth re-checking once answer-quality metrics exist.
- **4. Access filter inside the Qdrant query: kept (a security rule, not a quality gain).** Admin and a member licensed
  for all four products are identical to row 2. Public (not logged in) drops to Recall@10 0.692 because 6 tuning
  questions have only internal or restricted answer pages (all 6 are exactly the ones that were lost), so a public user
  must be told "not found". A member licensed for GitHub only (row 4c) gets back a little (0.712): the GitHub half of
  `x-06`, but none of the Kafka or Kubernetes internal pages. Tests prove nobody reads a non-public chunk of a product
  they are not licensed for, in any mode (`tests/test_access.py`, `tests/test_search_modes.py`, including a run over all
  40 questions on the real index).

Split: tune. Unanswerable questions skipped (no relevant page): 4. The 10 holdout questions have not been scored.

### Chunking and embedding experiments (passage level)

Question: is the answer stage starved because chunking, embedding or retrieval is weak? The page-level scores above cannot tell,
so `eval/run.py` now also scores **passages**: each question's labelled evidence quote must be inside a retrieved chunk
("Passage" columns), and inside the context the answer step would actually build from the top 5 chunks ("Answer in context").
26 answerable tuning questions, 52 evidence items, so one item is 0.019 and differences under about 0.05 are noise.
All indexes: Qdrant collections `exp_*`, built on the GPU in fp16 (so "Median ms" is not comparable with the table above).
Tables are `eval/results/small_grid_hybrid.md` and `embedding_compare.md`, made by `python -m eval.variants`.

Chunking, bge-small, hybrid retrieval (`size 500/250` = tokens; `headings` = the existing heading-aware chunker):

| Variant | Chunks | Avg chars | Page R@10 | Page MRR | Passage R@5 | Passage R@10 | Passage MRR | Answer in context | Median ms |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| fixed 500 | 2602 | 1872 | 0.904 | 0.825 | 0.712 | 0.750 | 0.619 | 0.635 | 69 |
| fixed 250 | 5007 | 965 | 0.904 | 0.884 | 0.635 | 0.712 | 0.476 | 0.673 | 85 |
| recursive 500 | 3467 | 1510 | 0.904 | 0.799 | 0.635 | 0.712 | 0.538 | 0.635 | 77 |
| recursive 250 | 6667 | 722 | 0.846 | 0.751 | 0.500 | 0.577 | 0.348 | 0.577 | 91 |
| headings 500 | 3816 | 1384 | 0.885 | 0.770 | 0.519 | 0.673 | 0.370 | 0.635 | 82 |
| headings 250 | 6778 | 713 | 0.846 | 0.725 | 0.442 | 0.558 | 0.298 | 0.596 | 94 |

Embedding model and reranker, on the same fixed-500 chunks (bge-m3 = `BAAI/bge-m3`, 1024 dimensions, run on GPU for indexing):

| Variant | Chunks | Avg chars | Page R@10 | Page MRR | Passage R@5 | Passage R@10 | Passage MRR | Answer in context | Median ms |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| bge-small dense | 2602 | 1808 | 0.904 | 0.763 | 0.692 | 0.712 | 0.538 | 0.615 | 32 |
| bge-m3 dense | 2602 | 1794 | 0.904 | 0.887 | 0.692 | 0.769 | 0.615 | 0.615 | 111 |
| bge-small hybrid | 2602 | 1872 | 0.904 | 0.825 | 0.712 | 0.750 | 0.619 | 0.635 | 69 |
| bge-m3 hybrid | 2602 | 1870 | 0.904 | 0.897 | 0.712 | 0.769 | 0.647 | 0.712 | 129 |
| bge-small hybrid+rerank | 2602 | 1939 | 0.904 | 0.822 | 0.731 | 0.788 | 0.467 | 0.654 | 1844 |
| bge-m3 hybrid+rerank | 2602 | 1917 | 0.904 | 0.824 | 0.731 | 0.808 | 0.472 | 0.654 | 1904 |
| fixed 250 + rerank | 5007 | 980 | 0.923 | 0.873 | 0.481 | 0.692 | 0.433 | 0.596 | 916 |
| headings 500 + rerank | 3816 | 1411 | 0.904 | 0.855 | 0.481 | 0.654 | 0.343 | 0.635 | 1793 |

What this shows:
- **No other chunking beat fixed 500 tokens** on passage recall. Recursive splitting is no better than fixed windows, and heading-aware
  chunks are no better either; 250-token chunks lose passage recall (more, smaller chunks crowd the top 10) although fixed 250 put
  more evidence into the context (0.673 vs 0.635, 2 items, within noise). The suspicion that 500 tokens is too small is not supported:
  bge-small reads at most 512 tokens, and 500 was the best of the sizes tried.
- **bge-m3 is better, modestly:** page MRR 0.825 -> 0.897, answer-in-context 0.635 -> 0.712 (4 items), passage recall@10 0.750 -> 0.769.
  It costs a 40-minute index build on this GPU (about 1 chunk/s, bge-small 13 chunks/s), a 17x larger model and 1024-dim vectors.
  The reranker lifts passage recall@10 but lowers passage MRR and does not add context evidence, so it stays off.
- **A bug in my own context builder was costing evidence** (found by looking at questions whose evidence was at rank 2): a neighbouring chunk
  was merged into the previous one without adding its text. Fixed, with a regression test. Before the fix, fixed-500 hybrid had 0.577 of the
  evidence in context; after it, 0.635.
- `text-embedding-3-small` was **not tested**: it is a paid cloud API (CLAUDE.md: free and local only, ask before anything paid).
- Not run: bge-m3 with the other five chunkings (about 40 minutes each; only worth it if you want the full grid).

### Query understanding (stage 7): rewrite, route, HyDE

One LLM call turns the question into a search plan (`src/query.py`): the products it concerns, 1-3 rewritten queries (one per product for
cross-product questions) and a hypothetical answer (HyDE). `search_plan()` searches with the plan and merges with RRF; the original question is
always one of the lists. `rewrite` = also search the rewritten queries, `route` = restrict to the routed product, `hyde` = also a meaning search with the
hypothetical answer. Plans are written by Groq (`openai/gpt-oss-120b`) or the local Qwen2.5-3B, cached on disk. Setup: bge-small, fixed 500, hybrid,
tuning split (26 answerable questions, 52 evidence items; one item = 0.019). `python -m eval.run --plan rewrite,route,hyde --plan-llm groq`;
table: `eval/results/query_plan_hybrid.md`.

| Variant | Page R@10 | Page MRR | Passage R@5 | Passage R@10 | Passage MRR | Answer in context | Product routing | Plan s |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| plain search (baseline) | 0.904 | 0.825 | 0.712 | 0.750 | 0.619 | 0.635 | n/a | n/a |
| Groq: rewrite | 0.885 | 0.864 | 0.673 | 0.712 | 0.652 | 0.635 | 1.000 | 0.68 |
| Groq: route | 0.904 | 0.825 | 0.712 | 0.750 | 0.612 | 0.635 | 1.000 | 0.68 |
| Groq: rewrite + route | 0.885 | 0.864 | 0.654 | 0.692 | 0.614 | 0.615 | 1.000 | 0.68 |
| Groq: hyde | 0.942 | 0.857 | 0.692 | 0.827 | 0.546 | 0.654 | 1.000 | 0.68 |
| Groq: rewrite + route + hyde | 0.904 | 0.864 | 0.654 | 0.788 | 0.629 | 0.615 | 1.000 | 0.68 |
| local Qwen 3B: rewrite | 0.904 | 0.729 | 0.615 | 0.769 | 0.499 | 0.577 | 0.885 | 4.56 |
| local Qwen 3B: route | 0.923 | 0.796 | 0.712 | 0.750 | 0.583 | 0.635 | 0.885 | 4.56 |
| local Qwen 3B: rewrite + route + hyde | 0.923 | 0.684 | 0.654 | 0.750 | 0.459 | 0.577 | 0.885 | 4.56 |
| local Qwen 3B: hyde | 0.923 | 0.766 | 0.712 | 0.750 | 0.540 | 0.558 | 0.885 | 4.56 |

- **No variant clearly helps.** "Answer in context" (the number that matters) stays between 0.56 and 0.65 against 0.635 for plain search.
  Groq HyDE has the best passage recall@10 (0.827 vs 0.750, 4 items) but a lower passage MRR (0.546 vs 0.619); rewrite helps page MRR (0.825 -> 0.864)
  but not passages. Combining all three is not better than the parts. Cross-product questions stay at 0.2-0.3 with routing and per-product sub-queries.
- **Routing itself works:** Groq named exactly the right products for 26 of 26 questions, the local 3B for 88.5% (it never named a wrong product, it missed
  one product on 3 questions). The local 3B plans are also worse as queries (e.g. it turned a disk-bloat question into `explain analyze select ...`),
  and take 4.6 s against 0.7 s for Groq.
- **The strict evidence label hides how well retrieval really does.** 5 questions never get the labelled passage into the context in any variant (3 more only partly); three of them were inspected:
  for `sym-02` (disk space after deletes) the top chunks are `routine-vacuuming` on recovering disk space with VACUUM FULL, for `sym-03` the right `populate` page, and for `x-05` the top chunk is the
  right ephemeral-storage page; both answer the question, but the labelled sentence is a different one on the same page. So 0.64 "answer in context" is
  a floor, not the true retrieval accuracy (page recall@10 is 0.90). Only a correctness judge can tell; that is the next step.
- The plan code stays in (`query.use: []` in `config.yaml` means plain search); nothing here justifies turning it on yet.
<!-- accuracy:start -->
### Answer accuracy: baseline of the current pipeline (Phase 1)

The user's metric: **accuracy = (answerable questions answered correctly + unanswerable questions refused) / all questions.** A judge (Groq
`qwen/qwen3.8-27b`, a different model family from the answer writer) compares each answer the user would see with the question's reference key
points (decision D2 in `docs/IMPROVEMENT_PLAN.md`); a partially correct answer does not count as correct. This is the **unchanged** pipeline:
local Qwen2.5-3B, bge-small, hybrid search, 5 chunks / 8,000 characters, NLI verifier at 0.3 (4 answers fell back to Groq `gpt-oss-120b` after a
local timeout: see the token table). Tuning split only; the holdout has not been run. `python -m eval.accuracy --name baseline`, copied from
`eval/results/accuracy_baseline_tune.md`:

**Accuracy: 21/70 = 30.0% (95% CI 20.5-41.5%)** on tune (70 questions: 58 answerable, 12 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 30.0% | 40.0% |
| Answerable answered correctly | 12 of 58 | 27 of 58 |
| Answerable partially correct (not counted as correct) | 5 of 58 | 10 of 58 |
| Answerable incorrect | 9 of 58 | 21 of 58 |
| Answerable refused (false refusals) | 32 of 58 | 0 of 58 |
| Unanswerable refused (correct) | 9 of 12 | 1 of 12 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 16 | 5 | 8 |
| symptom | 17 | 2 | 8 |
| version | 14 | 5 | 11 |
| cross_product | 11 | 0 | 0 |
| unanswerable | 12 | 9 | 1 |

**Failure breakdown** (49 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 12 |
| generation_error | 18 |
| verifier_false_refusal | 15 |
| unsafe_or_wrong_claim | 4 |

Of the 18 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 38 of 58 answerable questions. Shown answers with a wrong or dangerous claim: 6.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 4 | 4 | 7587 | 1259 | 8846 | 0 |
| groq/qwen/qwen3.8-27b | 84 | 84 | 49776 | 8643 | 58419 | 0 |
| local/qwen2.5-3b-instruct | 66 | 66 | 124097 | 8040 | 132137 | 0 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 5, max_context_chars 8000. Answer providers: {'local': 66, 'groq': 4}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: (none).

Run to run, with the answer step sampled again (`python -m eval.accuracy --name baseline_run2 --salt run2`; `python -m eval.spread baseline baseline_run2`,
copied from `eval/results/spread_baseline_vs_baseline_run2.md`; second run in `eval/results/accuracy_baseline_run2_tune.md`):

Same questions (70, tune split), two runs, verifier on:

- `baseline`: 21/70 = 30.0% (95% CI 20.5-41.5%); verifier off: 28/70 = 40.0% (95% CI 29.3-51.7%)
- `baseline_run2`: 26/70 = 37.1% (95% CI 26.8-48.9%); verifier off: 26/70 = 37.1% (95% CI 26.8-48.9%)
- difference: 5 questions (7.1 points)
- same outcome (correct or not) on 63 of 70 questions; correct in both 20, only in `baseline` 1, only in `baseline_run2` 6

| Failure category (verifier on) | `baseline` | `baseline_run2` |
|---|--:|--:|
| retrieval_miss | 12 | 11 |
| generation_error | 18 | 20 |
| verifier_false_refusal | 15 | 10 |
| unsafe_or_wrong_claim | 4 | 3 |

Can the judge be trusted? `python -m eval.judge --validate`, copied from `eval/results/judge_validation.md`. The 30 answers were labelled by the
assistant from the answer, the key points and the source text *before* it saw the judge's verdicts; labels and notes are in `eval/judge_labels.jsonl`.
A model checking a model overstates reliability, so a human spot-check of about 10 of the 30 is still worth doing.

Judge `qwen/qwen3.8-27b`, prompt v2, against 30 answers labelled by the assistant (docs/IMPROVEMENT_PLAN.md D4).

- Agreement on correct vs not correct: 29/30 = 96.7% (95% CI 83.3-99.4%)
- Agreement on the exact verdict: 27/30 = 90.0% (95% CI 74.4-96.5%)

| my label -> judge | count |
|---|--:|
| correct -> correct | 16 |
| correct -> incorrect | 1 |
| incorrect -> incorrect | 8 |
| partially_correct -> incorrect | 2 |
| partially_correct -> partially_correct | 3 |

How to read it:
- **The headline is low, and the judge is not the reason.** The plan guessed 45-55% because it counted every answer that was not refused as correct. Of the
  answerable questions, the verifier turns many into "No documented fix found." (see the false-refusal row), and many of the shown answers are wrong
  or incomplete. The judge agrees with the assistant's labels on correct vs not correct for 29 of 30 answers.
- **The verifier costs accuracy on answerable questions and buys it back on unanswerable ones.** First run: with it on, 9 of 12 unanswerable questions are
  refused (1 of 12 with it off), but 32 of 58 answerable questions are refused too (second run: 10 of 12 and 29 of 58). The "verifier off" column is the 3B model's draft.
- **Cross-product questions are the weakest type** (0 of 11 correct in the first run, 1 of 11 in the second) and also the ones where retrieval most often misses one of the two products.
- **Noise is large.** Two runs of the same pipeline differ by 5 questions (see above), and one question is 1.4 points, so a change has to move the
  headline by well over 7 points on this split to count. Every later phase is judged against both runs, not the better one.
- The failure categories are exclusive and checked in this order: verifier_false_refusal (the draft was correct, the verifier's answer is not), retrieval_miss
  (a labelled page group is missing from the context), unsafe_or_wrong_claim (an unanswerable question was answered, or the judge found a wrong claim in a shown answer), generation_error
  (the rest). Two `acceptable_pages` entries (`ver-07`, `x-06`) were added after the first baseline; they change the buckets, not the accuracy.
<!-- accuracy:end -->

<!-- phase2:start -->
### Answer accuracy after Phase 2: Groq writer, new answer format, wider context

Three changes at once (`docs/DECISIONS.md`, Phase 2), measured on the **dev subset** (40 of the 70 tuning questions, spread over the five types; the other
30 are still running, see below). The writer is Groq `gpt-oss-120b` (the local Qwen2.5-3B is only the failsafe). It answers in a format with a `kind` (fix /
explanation / fact / not_found), a short summary and cited points, and reads 10 chunks / 12,000 characters instead of 5 / 8,000. The verifier is **unchanged**
(the NLI model built for the 3B model); Phase 3 (below) replaces it. `python -m eval.accuracy --name p2_dev --dev`, copied from `eval/results/accuracy_p2_dev_tune.md`:

**Accuracy: 18/40 = 45.0% (95% CI 30.7-60.2%)** on tune (dev subset) (40 questions: 33 answerable, 7 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 45.0% | 82.5% |
| Answerable answered correctly | 11 of 33 | 26 of 33 |
| Answerable partially correct (not counted as correct) | 1 of 33 | 3 of 33 |
| Answerable incorrect | 0 of 33 | 3 of 33 |
| Answerable refused (false refusals) | 21 of 33 | 1 of 33 |
| Unanswerable refused (correct) | 7 of 7 | 7 of 7 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 9 | 4 | 9 |
| symptom | 10 | 2 | 7 |
| version | 8 | 5 | 8 |
| cross_product | 6 | 0 | 2 |
| unanswerable | 7 | 7 | 7 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 28 | 24 |
| partial | 4 | 2 |
| none | 8 | 7 |

**Failure breakdown** (22 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 2 |
| generation_error | 5 |
| verifier_false_refusal | 15 |
| unsafe_or_wrong_claim | 0 |

Of the 5 generation errors, 1 were the model refusing by itself. Evidence fully inside the context for 25 of 33 answerable questions. Shown answers with a wrong or dangerous claim: 0.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 40 | 40 | 131804 | 9413 | 141217 | 0 |
| groq/qwen/qwen3.8-27b | 44 | 44 | 27570 | 3606 | 31176 | 0 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 40}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: (none).

The same 40 questions, baseline vs Phase 2 (`python -m eval.spread baseline p2_dev --dev`, copied from `eval/results/spread_baseline_vs_p2_dev_dev.md`):

Same questions (40, the dev subset, tune split), two runs, verifier on:

- `baseline`: 11/40 = 27.5% (95% CI 16.1-42.8%); verifier off: 17/40 = 42.5% (95% CI 28.5-57.8%)
- `p2_dev`: 18/40 = 45.0% (95% CI 30.7-60.2%); verifier off: 33/40 = 82.5% (95% CI 68.0-91.3%)
- difference: 7 questions (17.5 points)
- same outcome (correct or not) on 31 of 40 questions; correct in both 10, only in `baseline` 1, only in `p2_dev` 8

| Failure category (verifier on) | `baseline` | `p2_dev` |
|---|--:|--:|
| retrieval_miss | 6 | 2 |
| generation_error | 11 | 5 |
| verifier_false_refusal | 10 | 15 |
| unsafe_or_wrong_claim | 2 | 0 |

How much of the labelled evidence reaches the writer, by context size (`python -m eval.run --k-context K --max-context-chars C --max-section-chars S`, then
`python -m eval.ctx_sweep`; no LLM involved; copied from `eval/results/context_sweep.md`; passage level, so strict):

| k_context | max_context_chars | max_section_chars | ctx_recall (all) | ctx_recall (cross_product) |
|--:|--:|--:|--:|--:|
| 5 | 8000 | 2800 | 0.716 | 0.318 |
| 6 | 10000 | 2000 | 0.767 | 0.318 |
| 8 | 10000 | 2000 | 0.767 | 0.318 |
| 8 | 10000 | 2800 | 0.733 | 0.318 |
| 8 | 12000 | 1500 | 0.724 | 0.364 |
| 8 | 12000 | 2000 | 0.784 | 0.409 |
| 10 | 10000 | 1500 | 0.707 | 0.273 |
| 10 | 10000 | 2000 | 0.750 | 0.318 |
| 10 | 12000 | 1500 | 0.724 | 0.364 |
| 10 | 12000 | 2000 | 0.810 | 0.455 |

How to read it:
- **The writer was the main limit.** With the verifier off, 33 of 40 answers are correct (the baseline's draft: 17 of 40), and the writer refuses all 7 unanswerable
  questions by itself. The judge found no wrong or dangerous claim in any shown answer.
- **With the old verifier on, accuracy is 45.0%, not 82.5%**: the NLI verifier refuses most of the good drafts (`verifier_false_refusal`), so the pipeline as configured
  is held back by its own check. That is what Phase 3 (an LLM claim check) is for; the "verifier off" column is not a shippable number because nothing then stops an invented claim.
- **Cross-product is still the weak type** and, with the new context, most of what is left besides the verifier is retrieval and a few generation errors.
- 40 questions give a wide interval (about +-14 points), and the baseline had a 7-point run-to-run spread; the 82.5% vs 42.5% gap is far outside both, the 45.0% vs 27.5% gap is not by much.
- **Not run:** `reasoning_effort: medium` (would cost another day of the 120b quota; `low` is in use), and the full 70-question tuning split (about 250k tokens, more than the 200k/day limit; it is
  running with `python -m eval.accuracy --name p2 --wait` and fills in as the quota window rolls over: `python -m eval.spread baseline p2` then compares the two on all 70).
<!-- phase2:end -->

<!-- phase3:start -->
### Answer accuracy after Phase 3: LLM claim check instead of the NLI verifier

Only the verifier changed (`docs/DECISIONS.md`, Phase 3). The NLI model is replaced by one Groq `gpt-oss-20b` call per answer that sees the question, the answer and only the
cited excerpts, and marks the summary and every point supported / partially supported / unsupported and whether the answer answers the question. Unsupported points are dropped;
the answer is refused if no point is left or it does not answer the question. The 120b answers are the cached ones from the Phase 2 dev run, so the writer is identical.
`python -m eval.accuracy --name p3_dev --dev`, copied from `eval/results/accuracy_p3_dev_tune.md`:

**Accuracy: 33/40 = 82.5% (95% CI 68.0-91.3%)** on tune (dev subset) (40 questions: 33 answerable, 7 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 82.5% | 82.5% |
| Answerable answered correctly | 26 of 33 | 26 of 33 |
| Answerable partially correct (not counted as correct) | 3 of 33 | 3 of 33 |
| Answerable incorrect | 3 of 33 | 3 of 33 |
| Answerable refused (false refusals) | 1 of 33 | 1 of 33 |
| Unanswerable refused (correct) | 7 of 7 | 7 of 7 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 9 | 9 | 9 |
| symptom | 10 | 7 | 7 |
| version | 8 | 8 | 8 |
| cross_product | 6 | 2 | 2 |
| unanswerable | 7 | 7 | 7 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 28 | 24 |
| partial | 4 | 2 |
| none | 8 | 7 |

**Failure breakdown** (7 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 2 |
| generation_error | 3 |
| verifier_false_refusal | 0 |
| unsafe_or_wrong_claim | 2 |

Of the 3 generation errors, 1 were the model refusing by itself. Evidence fully inside the context for 25 of 33 answerable questions. Shown answers with a wrong or dangerous claim: 3.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 40 | 40 | 131804 | 9413 | 141217 | 0 |
| groq/openai/gpt-oss-20b | 32 | 0 | 48508 | 5137 | 53645 | 53645 |
| groq/qwen/qwen3.8-27b | 64 | 61 | 41133 | 5453 | 46586 | 2124 |

Split: tune. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 40}. Verifier: llm (openai/gpt-oss-20b), used for: {'llm': 32, '': 8}. Judge qwen/qwen3.8-27b (prompt v2). Answer salt: (none).

Phase 2 against Phase 3 on the same 40 questions (`python -m eval.spread p2_dev p3_dev --dev`, `eval/results/spread_p2_dev_vs_p3_dev_dev.md`): 45.0% -> 82.5%; `verifier_false_refusal` 15 -> 0.

How to read it:
- **The verifier is no longer the bottleneck**: with the claim check on, accuracy equals the verifier-off draft (82.5%), all 7 unanswerable questions are still refused, and no good answer is lost.
- **It also changed almost nothing**: of 95 checked claims 87 were supported, 5 partially and 3 unsupported; 3 of the 40 shown answers differ from the draft, none was a net gain or loss in correctness.
  It did not stop the 3 shown answers the judge calls wrong (`sym-02`, `sym-15`, `x-04`): the checker marked their claims supported (`x-04`: partially supported, kept), while the judge finds them wrong for the question. Why was not investigated.
- **The refusal rule was not stress-tested**: the writer refused all 7 unanswerable questions by itself, so `answers_the_question: no` never had to stop a made-up answer here. That needs a test where the writer does answer.
- What is left is the writer and retrieval: 2 `retrieval_miss`, 3 `generation_error` and 2 wrong claims, mostly cross-product (2 of 6 correct) and symptom questions. Phase 4 targets these.
- 40 questions: +-14 points. Tokens: 54k on the 20b bucket for 32 checks (about 1.7k each).
<!-- phase3:end -->

<!-- phase4:start -->
### Phase 4 (started): retrieval for the remaining misses

Phase 4 has three parts (`docs/DECISIONS.md`); none beat the Phase 3 pipeline.
Retrieval at the Phase 2 context (10 chunks / 12,000 characters / sections up to 2,000; hybrid; 58 answerable tune questions), from `eval/results/ctx_k10_c12000_s2000_tune.md`, `p4a_m3_ctx_tune.md`, `p4c_prefix_ctx_tune.md`:

| Index | Page recall@10 | MRR | Passage recall@10 | Evidence in context | ... cross-product | Median search |
|---|--:|--:|--:|--:|--:|--:|
| bge-small (current) | 0.940 | 0.890 | 0.810 | 0.810 | 0.455 | 79 ms |
| 4a: bge-m3 | 0.931 | 0.905 | 0.793 | 0.767 | 0.500 | 210 ms |
| 4c: bge-small + title/heading prefix | 0.931 | 0.842 | 0.845 | 0.810 | 0.364 | 80 ms |

- **4a, bge-m3: not adopted.** Evidence-in-context falls overall (0.810 to 0.767; the 11 cross-product questions rise, 0.455 to 0.500, which is 0.5 of one question's evidence) and the question embedding is slower. Its earlier gain was measured at a 5-chunk context.
- **4c, contextual prefix: not adopted.** Evidence-in-context is unchanged; passage recall@10 rises but MRR and page recall@10 fall. Nothing here predicts a higher accuracy.
- **4b, retry loop: built, measured, switched off.** When the writer says its excerpts cover only part of the question: one more search with a query plan and the writer's own `missing` text, then one more answer.
  Dev subset (`eval/results/accuracy_p4b_dev_tune.md`): **80.0%** (32/40, CI 65.2-89.5%) against **82.5%** without it. It ran for 12 questions; the 7 unanswerable ones were still all refused; of 5 answerable ones 1 improved, 2 got worse, 1 turned a refusal into a wrong answer. No gain, so `retry.enabled: false`. 40 questions: 1 question = 2.5 points.
- **Phase 4 result: no change to the defaults.** Accuracy on the dev subset stays 82.5%.
<!-- phase4:end -->

<!-- phase5:start -->
### Final result (Phase 5): the holdout, run once

The holdout (38 questions never used for any choice) was run once with the frozen pipeline: Groq `gpt-oss-120b` writer, bge-small + BM25 hybrid search, 10 chunks / 12,000 characters, `gpt-oss-20b` claim check, retry off.
`python -m eval.accuracy --final --name final`, copied from `eval/results/accuracy_final_holdout.md`. The 8 original holdout questions got their key points, and 4 near-miss unanswerable questions were added, before this run (`docs/DECISIONS.md`, Phase 5). Questions and key points were written and checked by the assistant, not a human.

**Accuracy: 30/38 = 78.9% (95% CI 63.7-88.9%)** on holdout (38 questions: 26 answerable, 12 unanswerable).

| | Verifier on (pipeline as configured) | Verifier off (draft) |
|---|--:|--:|
| Accuracy (correct + correctly refused) / all | 78.9% | 78.9% |
| Answerable answered correctly | 18 of 26 | 18 of 26 |
| Answerable partially correct (not counted as correct) | 3 of 26 | 3 of 26 |
| Answerable incorrect | 4 of 26 | 4 of 26 |
| Answerable refused (false refusals) | 1 of 26 | 1 of 26 |
| Unanswerable refused (correct) | 12 of 12 | 12 of 12 |

| Question type | n | Correct (verifier on) | Correct (verifier off) |
|---|--:|--:|--:|
| error_message | 8 | 7 | 7 |
| symptom | 7 | 5 | 5 |
| version | 6 | 6 | 6 |
| cross_product | 5 | 0 | 0 |
| unanswerable | 12 | 12 | 12 |

The writer's own `coverage` flag against the draft (verifier off; unanswerable questions count as correct when refused):

| Writer says | Questions | Draft correct |
|---|--:|--:|
| full | 21 | 18 |
| partial | 4 | 0 |
| none | 13 | 12 |

**Failure breakdown** (8 questions not correct, verifier on):

| Category | Questions |
|---|--:|
| retrieval_miss | 3 |
| generation_error | 3 |
| verifier_false_refusal | 0 |
| unsafe_or_wrong_claim | 2 |

Of the 3 generation errors, 0 were the model refusing by itself. Evidence fully inside the context for 19 of 26 answerable questions. Shown answers with a wrong or dangerous claim: 2.

| Tokens behind these results | calls | of which cached | prompt | completion | total | spent in this run |
|---|--:|--:|--:|--:|--:|--:|
| groq/openai/gpt-oss-120b | 38 | 0 | 124395 | 8515 | 132910 | 132910 |
| groq/openai/gpt-oss-20b | 25 | 0 | 39200 | 3775 | 42975 | 42975 |
| groq/qwen/qwen3.8-27b | 50 | 24 | 32317 | 4678 | 36995 | 19458 |

Split: holdout. Role: admin. Collection support_docs (BAAI/bge-small-en-v1.5), k_context 10, max_context_chars 12000, max_section_chars 2000. Answer LLM groq (reasoning_effort low). Answer providers: {'groq': 38}. Verifier: llm (openai/gpt-oss-20b), used for: {'llm': 25, '': 13}. Judge qwen/qwen3.8-27b (prompt v2). Retry: off. Answer salt: (none).

How to read it:
- **78.9% (95% CI 63.7-88.9%)** is the number to quote; the dev-subset 82.5% was measured on the questions the pipeline was tuned on, and it is inside this interval.
- **Refusing is solid**: all 12 unanswerable questions were refused, including the 4 near-miss ones (a realistic but non-existent setting in a covered product).
- **Cross-product is the weak spot**: 0 of 5 correct (the dev subset had 2 of 6). The writer's own `coverage` flag was `partial` for 4 questions and none of those 4 drafts was correct.
- 8 misses: 3 retrieval, 3 generation, 2 wrong claims the claim check did not stop. 38 questions: one question is 2.6 points.
<!-- phase5:end -->

### Answer quality: verifier off vs on

`python -m eval.answer --name answer_v8_small --collection exp_fixed500_small --embedding BAAI/bge-small-en-v1.5` (copied from
`eval/results/answer_v8_small_tune.md` and `.json`; the default config: bge-small, fixed 500, hybrid, fixed context builder).
Tuning split: 26 answerable and 4 unanswerable questions, role admin, local Qwen2.5-3B (Groq fallback used 0 times), 5 chunks expanded to
parent sections. Both columns come from the **same** generated answers; only the verifier differs. The 2 unanswerable holdout questions are
not included (holdout is for the final run).

| | Verifier off | Verifier on |
|---|--:|--:|
| Steps shown (answerable questions) | 73 | 24 |
| Unsupported steps shown | 46 | 0 |
| Steps with no valid citation | 0 | 0 |
| Steps with a command word not in the docs | 1 | 0 |
| Unanswerable questions refused | 0 of 4 | 4 of 4 |
| Answerable questions refused | 0 of 26 | 15 of 26 |
| Answers blocked (secrets / personal data) | 0 | 0 |

How to read it:
- **"Unsupported" means the cited text does not entail the step (NLI score under 0.3 and under 70% copied from it, or no valid citation).**
  That is the verifier's own yardstick, so 0 in the "on" column is true by construction, not an independent proof. The independent check
  is the command-word row (words in inline code that appear nowhere in the retrieved docs). Nobody has labelled steps by hand yet.
- Without the verifier the 3B model answered **all 4** unanswerable questions with invented steps. With it, all 4 were refused.
- The price: **15 of 26 answerable questions** are refused too. With bge-m3 instead (`answer_v8_m3_tune.md`) it is 14 of 26: better retrieval
  did not fix this. Split by whether the labelled evidence was in the context (bge-m3 run): in 17 questions it was fully there and 7 of them
  were still refused; in 3 it was partly there (2 refused); in 6 it was missing (5 refused, which is the right call). So retrieval is no longer the
  main limit: the 3B model adds steps the docs do not state, and the strict verifier drops them. (That split is from a one-off script,
  not saved.) Across eight runs of near-identical code the refusal count was 13 to 15, so differences of 1 or 2 are noise.
- Threshold 0.3 was chosen on this same tuning split, so the numbers are somewhat optimistic. 4 unanswerable questions is a very small sample.
- The danger-command warning and the secrets/personal-data block did not trigger on any generated answer; they are checked by unit tests only.

## Who can see what (simulated access)

Three roles (`src/access.py`). The data is public docs, so the levels (public / internal / restricted) are assigned by
path rules in `configs/access_rules.yaml`; the rules below are real and tested.

| Role | Sees |
|---|---|
| **public** (not logged in) | `public` chunks of every product |
| **member** (logged in) | `public` chunks of every product, plus `internal` and `restricted` chunks of the products they hold a license for. A member with a GitHub license but no Kubernetes license gets GitHub answers in full and only public Kubernetes docs. |
| **admin** | everything; the only role that can add users and grant or revoke licenses |

Licenses (user, product, who granted it, when) live in SQLite (`data/access.db`) with an audit log, managed through
`AccessStore.grant / revoke / add_user` (admin only; a member cannot grant themselves anything). `AccessStore.principal(user_id)`
turns a user into what `search()` needs; unknown or missing users are public. Nothing proves who the caller is yet
(login is stage 7) and there is no admin dashboard yet (the UI comes later); the functions it will call exist and are tested.
In production the levels would come from the company's own docs metadata instead of the path rules.

## Evaluation

Test set: `eval/questions.jsonl`, **104 questions**: 24 exact error messages, 24 symptoms, 20 versions/facts, 16 across
products, 20 the docs cannot answer. **70 are for tuning** (58 answerable, 12 unanswerable) and **34 are a holdout** for the final run only
(`python -m eval.accuracy --final --name final`). A fixed 40-question **dev subset** of the tuning split (`"dev": true`) is for quick runs.
The first 40 questions were written and reviewed by a human; the 64 added in Phase 1 and all the key points of the tuning split were drafted by
Groq models and then checked against their source text and edited by the assistant (`verified_by: "assistant"`, with a `verify_note`; decision D4 in
`docs/IMPROVEMENT_PLAN.md`). A human has not re-checked them; the judge validation below has the same limit. The 10 original holdout questions are
untouched and still lack key points (they get them before the final run).
Each answerable question lists the right page(s), the section and a verbatim quote (used by the retrieval metrics: Recall@k = share of required
page groups found in the top-k chunks; MRR = 1 / rank of the first chunk from a correct page), and for the answer accuracy metric 1-4 reference
`key_points` (each essential or optional) and `acceptable_pages`. Unanswerable questions name a tool that occurs nowhere in the corpus (checked by a test).

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
public 1749, internal 596, restricted 257. Chunking: fixed 500 tokens, 50 overlap (`chunking.strategy: headings` is available but off, see Results).

Licenses and attribution: Kubernetes and GitHub Docs CC BY 4.0, Kafka Apache 2.0, PostgreSQL License,
Stack Overflow CC BY-SA 4.0 (see `docs/DATA_SOURCES.md`).

## Indexing and search (stages 5, 6, 8, 9 basic)

- 2602 chunks embedded with `BAAI/bge-small-en-v1.5` (CPU) and stored in Qdrant collection `support_docs`
  with their metadata. Re-running `src.index` embeds nothing new and creates no duplicates (tested).
- The embedding model name is stored in the collection. Search and indexing stop with
  `EmbeddingModelMismatch` if `config.yaml` names a different model.
- `src.search.search(question, k, product, principal, mode)` returns the top-k chunks the principal may read (default: public).
  `mode`: `dense`, `hybrid` (dense + BM25 merged with RRF, the default) or `rerank` (hybrid + cross-encoder on the top 30).
  Who can see what: see the access section above.
  The access filter is part of the Qdrant query and is applied before BM25 ranking, so hidden chunks never reach RRF or the reranker.
- Retrieval metrics: see Results (`python -m eval.run --name <name> --mode dense|hybrid|rerank --role public|member|admin [--licenses github,kafka]`).
- Known issue: Stack Overflow titles/text still contain HTML entities such as `&quot;` (ingest cleanup TODO).
