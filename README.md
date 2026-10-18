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

Retrieval, one change at a time. Tuning split, 26 answerable questions, top 10 chunks searched. Every number is
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
Answer-quality metrics (citations, refusals): none yet.

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

Test set: `eval/questions.jsonl`, 40 questions (10 exact error messages, 10 symptoms, 8 versions, 6 across
products, 6 the docs cannot answer), all marked `verified=true` after human review. 30 are for tuning, 10 are a holdout
for the final run only (`python -m eval.run --final --name final`). Each answerable question lists the right page(s),
the section and a verbatim quote. Scoring is page-level: Recall@k = share of required page groups found in the top-k
chunks; MRR = 1 / rank of the first chunk from a correct page (top 10 searched). The 4 unanswerable tuning questions
have no correct page, so they are skipped here; they matter once refusing is built.

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
