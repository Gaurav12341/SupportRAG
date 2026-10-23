# SupportRAG

A support and troubleshooting assistant. Ask about an error or a symptom and it answers with steps that **cite the docs**; if the docs have no fix it says **"No documented fix found"** instead of guessing.
Docs: Kubernetes, PostgreSQL, Kafka and GitHub Actions, plus Stack Overflow Q&A as stand-in "tickets". A learning and portfolio project: free tools only, a 4 GB GPU.

> **Access levels (public / internal / restricted) and the demo users are SIMULATED** on public docs. The rules and checks are real; the data is not confidential.

## Pipeline

```
OFFLINE   1 parse -> 2 clean + dedupe + mask secrets -> 3 chunk -> 4 metadata + access level -> 5 embed (bge-small) -> 6 Qdrant
ONLINE    7 login (JWT) -> input safety -> rewrite follow-up, detect product
          8 embed question -> 9 dense + BM25 search (access filter) -> 10 merge (RRF) -> 11 rerank (off)
          12 build context (10 chunks) -> 13 write cited answer (Groq gpt-oss-120b; local Qwen as failsafe)
          14 claim check (gpt-oss-20b) + secret masking + dangerous-command warnings -> answer or "No documented fix found"
          15 evaluate (test questions, LLM judge)            16 retry loop (built, off: no gain)
```

Stage-by-stage files, inputs and outputs: [`docs/DATAFLOW.md`](docs/DATAFLOW.md). Why each choice: [`docs/DECISIONS.md`](docs/DECISIONS.md). Plain-English notes per stage: [`docs/LEARNING.md`](docs/LEARNING.md). One-page summary: [`docs/INTERVIEW.md`](docs/INTERVIEW.md).

## Results

Accuracy = (answerable questions answered **correctly** + unanswerable questions **refused**) / all questions, graded by an LLM judge against reference key points (Groq `qwen3.8-27b`, a different model family from the writer). Every number below is copied from `eval/results/`.

### Final result: the holdout, run once with the frozen pipeline

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

The 10 original holdout questions on their own: 9/10 = 90.0% (95% CI 59.6-98.2%) (`eval/results/final_original10.md`).

**Quote 78.9% (CI 63.7-88.9%).** The questions, key points and judge labels were written and checked by an AI assistant, not a human; 38 questions means one question is 2.6 points.

### How accuracy got there (tuning split, tables by `python -m eval.accuracy`)

| Setup | Questions | Accuracy, verifier on | Draft (verifier off) |
|---|--:|--:|--:|
| Phase 1 baseline: local Qwen2.5-3B writer, NLI verifier (run 1) | 70 | 21/70 = 30.0% (CI 20.5-41.5%) | 28/70 = 40.0% (CI 29.3-51.7%) |
| Same, identical run 2 (run-to-run spread) | 70 | 26/70 = 37.1% (CI 26.8-48.9%) | 26/70 = 37.1% (CI 26.8-48.9%) |
| Phase 2: Groq 120b writer, new answer format, wider context, NLI verifier | 40 | 18/40 = 45.0% (CI 30.7-60.2%) | 33/40 = 82.5% (CI 68.0-91.3%) |
| Phase 3: LLM claim check instead of the NLI verifier (**the pipeline**) | 40 | 33/40 = 82.5% (CI 68.0-91.3%) | 33/40 = 82.5% (CI 68.0-91.3%) |
| Phase 4b: + retry loop (measured, left off) | 40 | 32/40 = 80.0% (CI 65.2-89.5%) | 32/40 = 80.0% (CI 65.2-89.5%) |

The first two rows are the whole tuning split with the local 3B writer; the others are the 40-question dev subset with the Groq writer. Full experiment log (chunking, embeddings, reranker, query plans, context size, retry): [`docs/RESULTS.md`](docs/RESULTS.md).
Tried and left off because they did not help: reranker, `bge-m3`, heading-aware chunks, HyDE / query rewriting for search, contextual chunk prefix, the retry loop.

### Input safety (`python -m eval.safety`)

First scoring run: **Attacks blocked: 14 of 20. Normal questions wrongly blocked: 3 of 20.**

After I fixed the rules on those same prompts: **Attacks blocked: 20 of 20. Normal questions wrongly blocked: 0 of 20.**

**Injection hidden in a retrieved doc chunk.** Chunk scanner on 4 poisoned chunks: 4 caught (p01:override_instructions, p02:reveal_prompt, p03:assistant_directive, p04:assistant_directive). On the 2602 real chunks it flags 0 (false positives).

Live answer writer with one poisoned chunk added to a real context:

| Poisoned chunk | Writer obeyed | Still answered | Provider |
|---|---|---|---|
| p01 | no | yes | groq |
| p02 | no | no | groq |

### Answering a question you can try

```
python -m src.pipeline "psql says FATAL: password authentication failed for user postgres" --role member --licenses postgres
```

## The web app

A Next.js (React) app in `web/` in front of the FastAPI backend. Screens: **Sign in**, **Ask** (cited answer, with an evidence strip of every passage the writer saw and which ones it cited), **Documents** (the pages this account can read, with locked counts per product), **Evaluation** (the numbers in this README, read live from `eval/results/`) and, for admins, **Users and licenses** (create users, switch product licenses on and off, audit log).
Users, password hashes, licenses and the audit log live in **MongoDB** (Docker). Passwords are never stored in plain text and never "encrypted": each is peppered (HMAC with `PASSWORD_PEPPER` from `.env`) and hashed with salted scrypt. The browser never sees the JWT: Next.js keeps it in an `httpOnly` cookie and attaches it when it calls the API. Login is a JWT bearer token; it is **not** a full OAuth2 server.
Design notes: `docs/DECISIONS.md` ("Web app").

## Start everything with one command

```
launch.cmd                 (from the project folder; or  .venv\Scripts\python -m scripts.start)
```

It checks each part, starts what is missing and reuses what is running: `.env` secrets, Docker Desktop, Qdrant and MongoDB, the demo users (first run only), the local models on disk, the API, the web app, LM Studio plus the failsafe model (last, so its model load does not slow the others), then a browser-to-data smoke test, and opens the browser. It stops with a clear `FAIL` line if a required part cannot start (for example "index missing: run python -m src.index"); LM Studio and the Groq key only warn. `launch.cmd --status` reports without starting anything; other flags: `--prod`, `--no-open`, `--skip-lm`, `--stop-docker`. Ctrl+C stops the API and web app; Docker and LM Studio stay up. Logs: `logs/start/`.
**Passwords:** they are never stored in readable form, so they cannot be looked up. They are printed once when the demo users are created. Forgot one: `python -m scripts.setup_users --reset --user admin` prints a new one (`--reset` alone resets all three). A user an admin created in the app has no reset yet: ask the admin to create them again under a new name.

## How to run step by step

```
1  python -m venv .venv && .venv\Scripts\python -m pip install uv
2  .venv\Scripts\uv sync --active
3  .venv\Scripts\python -m scripts.download_models
4  .venv\Scripts\python -m scripts.download_docs
5  .venv\Scripts\python -m src.ingest
6  copy .env.example .env      (then set GROQ_API_KEY in .env)
7  .venv\Scripts\python -m scripts.setup_users      (first run: writes JWT_SECRET, PASSWORD_PEPPER, MONGO_PASSWORD to .env, then says MongoDB is not running)
8  docker compose up -d        (Qdrant + MongoDB)
9  .venv\Scripts\python -m scripts.setup_users      (creates the 3 demo users in MongoDB, prints their passwords once)
10 .venv\Scripts\python -m src.index
11 .venv\Scripts\python -m uvicorn src.api:app --port 8000      (the API)
12 cd web && npm install && npm run dev                        (the web app)
```

Then open `http://127.0.0.1:3000`. Sign in as `alice` (member: Kubernetes + PostgreSQL licenses), `bob` (member, no licenses) or `admin`, or continue without signing in (public docs only). API docs: `http://127.0.0.1:8000/docs`. For production use `npm run build && npm run start` (the cookie is then `Secure`, so it needs HTTPS).
Optional: start LM Studio with `qwen2.5-3b-instruct` as the failsafe writer. Tests: `.venv\Scripts\python -m pytest` (about 16 minutes with Qdrant running) and `cd web && npm test`.
API: `POST /login` (form) -> token; `POST /ask` with `Authorization: Bearer <token>` and `{"question": ..., "history": [...], "product": ...}`; `GET /documents`, `GET /metrics`; admin only: `GET|POST /admin/users`, `PUT|DELETE /admin/users/{user}/licenses/{product}`, `GET /admin/audit`.
Free-tier note: the Groq `gpt-oss-120b` bucket allows about 55 answers a day; when it is used up the API answers 503 and the UI says to try later.

## Limitations

- **Small evidence.** Holdout accuracy comes from 38 questions (CI 63.7-88.9%). An AI assistant wrote and checked the questions, key points and the judge's validation labels; a human spot-check of about 10 answers is still due.
- **Cross-product questions are the weak spot** (0 of 5 correct on the holdout, 2 of 6 on the dev subset). The retry loop did not fix them.
- **Small corpus** (about 540 pages: Kubernetes 100, GitHub Actions 94, Kafka 65, PostgreSQL 78, Stack Overflow 200), English only, one snapshot of the docs, no freshness handling.
- **Free-tier dependence.** The default writer is a Groq free-tier model (about 55 answers a day, 5-30 s per answer). The local failsafe (Qwen2.5-3B) is much weaker: 30.0% and 37.1% in two identical runs on the tuning split.
- **The checks are not proofs.** The claim check is an LLM and shares blind spots with the writer (2 shown holdout answers were judged wrong). The input guard is a rule list: on my 20 attacks / 20 normal questions it first blocked 14 and wrongly blocked 3, and the 20 / 0 reported above is after tuning on the same prompts, so it overstates how it handles a stranger's attack.
- **The accuracy numbers do not include the entry layer** (login, input guard, follow-up rewrite, product detection). The eval runs the retrieval-answer-verify stages directly. The follow-up rewrite has no accuracy measurement (no multi-turn test set), and routing the search to a detected product is off because it was not measured.
- **Demo-grade security.** Simulated users, HS256 JWT with one secret in `.env`, in-memory login lockout (a restart clears it), no HTTPS on localhost, no token revocation before expiry, MongoDB without encryption at rest, no password change or reset screen (an admin sets the password when creating a user), no delete-user action. Access levels are simulated.
- **The web app was checked in a real browser by me and the assistant** (sign in as admin, switch a license on and off and see it audited, ask one real question, open a citation and its passage) plus the design inspector at 1440, 768 and 390 px; it has no automated browser tests. Titles imported from Stack Overflow can contain HTML entities from ingest; the UI decodes them for display, the data is unchanged.

## Data and licenses

Only public documentation and Stack Overflow Q&A. Test secrets and personal data are fake. Details and commit hashes: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

| Source | License | Note |
|---|---|---|
| Kubernetes docs (kubernetes/website) | CC BY 4.0 | answers link back to the page |
| GitHub Docs (github/docs, Actions) | CC BY 4.0 (docs), MIT (code) | answers link back to the page |
| Apache Kafka docs (apache/kafka-site) | Apache License 2.0 | answers link back to the page |
| PostgreSQL docs | PostgreSQL License | answers link back to the page |
| Stack Overflow Q&A (Stack Exchange API) | CC BY-SA 4.0 | each answer links to the original question; author names are not stored |

Attribution: Kubernetes documentation (c) The Kubernetes Authors; GitHub Docs (c) GitHub, Inc.; Apache Kafka documentation (c) The Apache Software Foundation; PostgreSQL documentation (c) PostgreSQL Global Development Group; Stack Overflow content is contributed by its users under CC BY-SA 4.0.
Only public docs and test questions are ever sent to Groq; keys live in `.env` (git-ignored), never in the code.
