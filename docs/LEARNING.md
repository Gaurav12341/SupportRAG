# LEARNING

For each stage built: 1. What is it? 2. How does it work here? 3. Why do we need it?
4. How do we measure it? 5. What goes wrong and how do we fix it?

## Stage 1: Parse

1. **What:** turn raw files (markdown, HTML, JSON) into plain text that still has headings, code blocks and tables.
2. **Here:** git repos give markdown; we strip Hugo/Liquid tags. PostgreSQL HTML and Stack Overflow go through a small BeautifulSoup converter.
3. **Why:** the model and the search should see content, not template tags or page chrome. Code and tables carry the actual fixes.
4. **Measure:** pages per source, and reading samples. Test: headings, code and tables survive.
5. **Wrong:** leftover `{{ }}` tags or lost tables. Fix: add a rule for the tag. (`${{ }}` in GitHub code is real content, not a leftover.)

## Stage 2: Clean, dedupe, mask

1. **What:** remove menus/footers, drop exact duplicate pages, hide emails, phones, keys and tokens.
2. **Here:** regex lists in `clean.py`; a page hash catches duplicates; placeholders like `example.com`, `xxxx`, `${VAR}` are kept.
3. **Why:** secrets must never reach the index or Groq; duplicates waste search slots and crowd out other results.
4. **Measure:** masked count by type (report), unit tests with fake secrets, and a read of what was masked.
5. **Wrong:** false positives (`action@v3.0.0` looked like an email) or misses. Fix: tighten the regex, add a test for the case.

## Stage 3: Chunk

1. **What:** cut each page into pieces small enough to embed and retrieve.
2. **Here:** fixed 500-token windows, 50 tokens overlap, counted with the embedding model's tokenizer.
3. **Why:** the embedder reads at most 512 tokens, and a small piece makes a precise answer to cite.
4. **Measure:** chunk count, token sizes (max 500), and above all retrieval Recall@k / MRR in the eval; a chunking change only counts if those improve.
5. **Wrong:** cuts fall mid-sentence or between a command and its explanation. We tried splitting on headings (code blocks and tables kept whole, `chunking.strategy: headings`): it made chunks tidier but retrieval scores did not improve (more, smaller chunks of one page crowd the top 10), so fixed windows stay for now.

## Stage 4: Metadata and access level

1. **What:** tag every chunk with product, version, source path, URL, doc type, license and a simulated access level.
2. **Here:** the page's source decides product/version; `configs/access_rules.yaml` decides the level (first matching rule wins).
3. **Why:** filters (product, access) and citations need this data on every chunk.
4. **Measure:** chunk counts per level and type; tests for rule matches.
5. **Wrong:** a page lands in the wrong level or type. Fix: edit the rules file and re-run; no code change.

## Stage 5: Embed

1. **What:** turn each chunk of text into a list of 384 numbers so similar meanings end up close together.
2. **Here:** `bge-small-en-v1.5` on CPU, vectors normalized to length 1. Documents are embedded as-is.
3. **Why:** it lets us find a chunk that says "container keeps restarting" for a question about "CrashLoopBackOff", without sharing words.
4. **Measure:** retrieval hit rate on the eval questions (stage 15, not built yet). Today: only eyeballing results.
5. **Wrong:** exact strings (error codes, flag names) match loosely, e.g. a long Postgres FATAL message did not return the `max_connections` page first. Fix: add BM25 and merge (stages 9-10).

## Stage 6: Store in Qdrant

1. **What:** a database that keeps every vector plus its metadata and can find the nearest ones fast.
2. **Here:** one collection; point id comes from the chunk id; the embedding model name is saved in the collection.
3. **Why:** embedding 2602 chunks on CPU is slow, so we do it once and reuse it. Re-runs must not pile up copies.
4. **Measure:** point count equals chunk count (2602 = 2602); a second run embeds 0 chunks. Both are tested.
5. **Wrong:** vectors from two different models mixed in one collection give nonsense scores. Fix: the name check refuses it; `--recreate` rebuilds.

## Stages 8-9 (basic): Embed the question and search

1. **What:** embed the question the same way, then ask Qdrant for the k closest chunks, optionally only one product.
2. **Here:** `search(question, k, product)` adds bge's question prefix, checks the model name, returns score + metadata + text.
3. **Why:** this is the base every later stage (BM25, merge, rerank) builds on.
4. **Measure:** recall@k on the eval set later. Scores here are cosine similarity and are only comparable within the same model.
5. **Wrong:** vague questions return plausible but off-topic chunks (see the "deployment will not start" example). Fix: question rewriting, product picking, reranking, and a "not enough evidence" threshold.

## Stage 9 (full): Retrieve with a keyword search and the role filter

1. **What:** two searches over the same chunks: by meaning (embeddings) and by words (BM25), both restricted to what the caller may read (role + product licenses).
2. **Here:** `search()` asks Qdrant for the top 20 by meaning with `access_level IN (role levels)` inside the query; BM25 (`rank-bm25`, built in memory from Qdrant's payloads) drops disallowed chunks before ranking and returns its top 20. Roles (simulated data, real rules): public sees public chunks; a member also sees internal/restricted chunks of the products they are licensed for; admin sees all and manages licenses (`src/access.py`).
3. **Why:** meaning search misses rare literal words (`kafka-streams-scala`, `runs.using`), word search misses paraphrases; and access rules must hold before ranking, otherwise a hidden chunk can still shape the results or leak in a snippet.
4. **Measure:** Recall@k and MRR per question type with `eval.run --mode dense|hybrid --role ...`; access safety by tests that nobody gets a non-public chunk of a product they are not licensed for (even when asking with that chunk's own text) in every mode, and that the Qdrant filter and the BM25 filter pick the same chunks.
5. **Wrong:** BM25 adds nothing when dense already finds the answer (exact error messages here: no gain); a post-filter would return fewer than k and risks leaks; a public user (or a member without the license) legitimately loses recall on questions whose answers are non-public. Fix: filter inside the query, fail closed on unknown roles/products, and make the answer step say "not found" instead of guessing.

## Stage 10: Merge results (RRF)

1. **What:** combine the two ranked lists into one.
2. **Here:** Reciprocal Rank Fusion: each chunk scores the sum of 1/(60 + rank) over the lists it appears in; chunks found by both float up.
3. **Why:** cosine similarity and BM25 scores are on different scales; ranks can be added without tuning weights.
4. **Measure:** MRR and Recall before/after (README Results row 2: MRR 0.763 -> 0.825).
5. **Wrong:** one weak list can still pull in noise, and with few questions a gain of a rank or two is hard to tell from luck. Fix: compare per question (`eval.compare`), not only the average.

## Stage 11: Rerank

1. **What:** a second, slower model reads the question and each candidate chunk together and re-scores them.
2. **Here:** `cross-encoder/ms-marco-MiniLM-L-6-v2` on CPU re-scores the top 30 merged chunks; the best 5 would go to the answer step. It is built but off by default.
3. **Why:** it judges relevance more carefully than embeddings, which compare precomputed vectors; its score can also back a "refuse if unsure" threshold later.
4. **Measure:** MRR/Recall vs hybrid, plus latency: MRR 0.825 -> 0.822, Recall@5 +0.038, 125 ms -> 3197 ms per search.
5. **Wrong:** it is slow on CPU and, on 26 questions, did not measurably help retrieval; it also only sees the 30 candidates it is given. Fix: leave it off until answer-quality metrics show a benefit, or shrink `k_rerank_in`.

## Stage 15 (step 1 of 2): the test questions

1. **What:** a fixed list of questions with known right pages, so we can score the system instead of judging by eye.
2. **Here:** 40 questions in 5 types; each cites the page, section and a verbatim quote. 6 have no answer in the docs on purpose. 10 are held back for the final run.
3. **Why:** without it, every tuning change is a guess, and "it feels better" is not a result.
4. **Measure:** the questions themselves are checked by a test (quotes exist, unanswerable terms are absent). The retrieval scores come in step 2.
5. **Wrong:** wrong labels make good retrieval look bad (or the reverse), and tuning on the holdout makes the final number too rosy. Fix: you review the labels first; the holdout stays untouched until the final run.

## Stage 15 (step 2 of 2): the retrieval eval script

1. **What:** a script that asks the search every test question and checks whether the right doc page came back, and how high.
2. **Here:** `eval/run.py` retrieves 10 chunks per question, maps each to its page, and computes Recall@5, Recall@10 and MRR per question type.
3. **Why:** it turns "search seems fine" into a number we can compare before and after each change (BM25, RRF, rerank).
4. **Measure:** the baseline table in the README; the metric maths is unit-tested with hand-computed cases.
5. **Wrong:** a small set makes numbers jumpy, and when Recall@5 equals Recall@10 it can no longer tell variants apart. Fix: judge by MRR and the weak rows (cross-product), add questions later, and use the holdout only once.

## Stage 12: Build the context

1. **What:** choose which text the model gets to read: the best chunks, grown to the section they sit in, without repeats.
2. **Here:** `src/context.py` takes the top 5 hybrid hits, finds each chunk's section in the page (heading to next heading), merges overlapping sections, keeps the strongest first and stops at about 8000 characters. Labels S1, S2... are attached.
3. **Why:** a 500-token window often cuts a procedure in half; a whole section keeps the steps together. Repeats waste the small context of a 3B model. A bigger writer can read more, so its profile takes 10 chunks / 12,000 characters with sections capped at 2,000 (measured: evidence in context 0.716 -> 0.810); more distinct places beat longer sections.
4. **Measure:** unit tests for section finding, merging, the size cap and the access drop. Answer quality is measured end to end (see Stage 14).
5. **Wrong:** a section can be huge or a page can have no headings, so the section gets cut or falls back to the chunk; too much context also confuses a small model. Fix: the size caps in `config.yaml`.

## Stage 13: Generate the answer

1. **What:** the LLM writes a short cited answer: a summary and points, each point naming the excerpt it came from.
2. **Here:** `src/answer.py` sends the excerpts (wrapped as data) and the question to the writer, Groq `gpt-oss-120b` (local Qwen2.5-3B is the failsafe, every fallback logged); the reply must match a JSON schema `{kind, coverage, missing, summary, points: [{text, sources}]}`. `kind` is fix / explanation / fact / not_found, so a version question gets one fact and a why-question gets a cause, instead of everything being forced into steps. `coverage` and `missing` say what the excerpts lack (for the retry loop later).
3. **Why:** citations let a person check each step; the schema forces the model to give them (free text skipped them too often).
4. **Measure:** end-to-end accuracy (Stage 15, answers) and, per answer, tokens: about 3.5k on the 120b bucket. The 3B writer got 42.5% of the dev questions right as a draft, the 120b writer 82.5% (same questions, same judge).
5. **Wrong:** a small model still invents generic advice, may cite the wrong excerpt, or obey text inside an excerpt. Fix: the verifier, the "excerpts are data" rule, and neutralising `</doc` in excerpts.

## Stage 14: Verify and output safety

1. **What:** after the model answers, check the answer before the user sees it: are the citations real, does the cited text back each point, does the answer address the question, is anything secret or dangerous in it.
2. **Here:** `src/answer.py` first checks every cited id is in the context and readable by the caller. Then **one** small-LLM call (`src/verify.py` `claim_check`, Groq `gpt-oss-20b`, temperature 0, cached) gets the question, the answer and only the cited excerpts and marks the summary and each point supported / partially_supported / unsupported, plus whether the answer answers the question (yes / partly / no). Unsupported points are dropped; no point left or "no" means "No documented fix found."; "partly" is shown with a note. If the LLM is down, the old NLI scorer (cited text entails the point, or it is mostly copied) checks that answer instead and the fallback is logged. `src/safety.py` withholds answers with secrets/personal data, adds WARNING lines to `kubectl delete`, `DROP TABLE` and Kafka topic deletes.
3. **Why:** a support answer that sounds right but is invented is worse than "not found"; a dangerous command pasted without a warning can do real harm; and a citation must never point to a document the user cannot open. The NLI model could not be the judge of a strong writer: it scores commands, code and list items near 0 even when copied from the docs, and it saw each step without the question.
4. **Measure:** `python -m eval.accuracy`: accuracy with the verifier on and off, the `verifier_false_refusal` count (draft correct, shown answer refused), refusal of the unanswerable questions, and wrong claims in shown answers (README, Phase 3).
5. **Wrong:** the checker can be too strict (drops true points, refuses good drafts) or too lenient (lets an answer to an unanswerable question through). Fix: look at the `claim` / `why` of each point in `eval/results/accuracy_*.json`; if unanswerable questions slip through, tighten the `answers_the_question` rule in the prompt, not the point check. It is another LLM, so it shares blind spots with the writer; the judge is a third model on purpose.


## Stage 3 and 5 revisited: chunking and embedding experiments

1. **What:** we compared other ways to cut pages (smaller windows, recursive splitting, heading-aware) and a bigger embedding model (bge-m3), to see if weak retrieval was why answers were poor.
2. **Here:** each variant gets its own Qdrant collection (`exp_*`) and is scored by `eval.run` at page level and at passage level (is the labelled evidence quote inside the retrieved chunk, and inside the context the answer step builds).
3. **Why:** page-level scores said retrieval was fine (0.90) while about 40% of the answer evidence never reached the model; only a passage-level check shows that.
4. **Measure:** passage recall@5/10, passage MRR and answer-in-context in `eval/results/small_grid_hybrid.md` and `embedding_compare.md`. Chunks of 250 and 500 tokens, recursive and heading-aware were compared; fixed 500 stayed best. bge-m3 helped a little (answer-in-context 0.635 -> 0.712).
5. **Wrong:** a small test set (52 evidence items) cannot separate gains under about 0.05; bigger chunks hold evidence more easily so size must be reported; and a bug in our own context builder (dropping a neighbouring chunk's text) hid evidence that retrieval had found. Fix: look at individual misses, add a regression test, and re-run the numbers after the fix.


## Stage 7 (query part): rewrite, route, HyDE

1. **What:** before searching, an LLM turns the user's wording into a better search: cleaner queries, the right product, one query per product for cross-product questions, and an imagined answer to search with (HyDE).
2. **Here:** `src/query.py` makes the plan (Groq or local Qwen, cached); `search_plan()` runs the original question plus the plan's searches and merges them with RRF. The original question is always kept, so a bad plan cannot remove good results.
3. **Why:** people describe symptoms in words the docs never use ("tables take more disk space" vs "VACUUM, dead tuples"), and a question about Kafka on Kubernetes needs a search in each product.
4. **Measure:** passage recall, passage MRR and answer-in-context per plan part, plus how often the routing names exactly the right products (Groq 26 of 26, local 3B 88.5%).
5. **Wrong:** the plan can drift from the question (the local 3B did), HyDE can invent facts that pull in wrong passages, and every plan costs an LLM call (0.7 s Groq, 4.6 s local). Here none of it beat plain search on the strict metric, and the metric itself under-counts (a different chunk of the right page can answer the question), so the next fix is a better judge, not a better rewrite.


## Stage 15 (answers): accuracy, the judge and the failure breakdown

1. **What:** measure whether the answers a user sees are *right*, not just whether they are backed by the text they cite. The score is (answerable questions answered correctly + unanswerable questions refused) / all questions.
2. **Here:** every test question has a few reference `key_points` (what a correct answer must say; "essential" ones decide). `eval/accuracy.py` runs the real pipeline, then `eval/judge.py` asks a different model family (Groq Qwen 27B) which key points the answer states and whether it contains a wrong claim; code turns those flags into correct / partially correct / incorrect. A refusal needs no judge: right for an unanswerable question, a miss for an answerable one. Each wrong answer is put in one bucket: retrieval miss, generation error, verifier false refusal, or unsafe/wrong claim.
3. **Why:** the earlier "unsupported steps" number used the verifier's own model to grade the verifier, and "not refused" is not "correct". Without a real accuracy number every change is a guess, and the buckets say where to work next.
4. **Measure:** accuracy with a 95% Wilson interval (21 of 70 is 30.0% with an interval of 20.5-41.5%, about +-10 points), per question type, the buckets, and the judge itself: 30 answers labelled by hand before looking at the judge, agreement on correct-vs-not (96.7% here, required 90%). Run the answer step twice to see the run-to-run spread.
5. **Wrong:** the judge can be too strict or too loose, and a model grading with a model's labels flatters itself (a human should spot-check some). Reference points can be too literal (`err-21`) or too narrow when a question has several valid fixes (written as "at least one of"). A small set hides differences: one question is 1.4 points. Fix: validate the judge first, keep the failure buckets next to the headline number, never tune on the holdout.


## Stage 16: the retry loop

1. **What:** when the first answer says "the excerpts only cover part of your question", search again, smarter, and answer once more instead of giving a half answer or a refusal.
2. **Here:** the writer reports `coverage` (full / partial / none) and `missing` (what it could not find) with every answer. If coverage is partial or none, `src/answer.py` `retry` asks a small model for a query plan (rewritten queries per product, a hypothetical answer), adds the `missing` text as one more query, searches with all of them, merges the new hits with the first ones (RRF) and gives the writer a slightly bigger context. Only one retry. The second answer is used only if it has points; a refusal on retry keeps the first draft. Everything is cached and logged (`RETRY ...`).
3. **Why:** the weak spot is cross-product questions ("how do I do X in Kafka and Y in Postgres"): one search fetches one product. The writer already knows which part is missing, so its own words are the best second query.
4. **Measure:** `python -m eval.accuracy` with and without `--no-retry`: accuracy, how many questions were retried, how many of those ended correct, and that the unanswerable ones are still refused. Tokens: the second pass costs about one more answer call (3.5-5k on the 120b bucket) plus a plan (about 1k on 20b).
5. **Wrong:** a retry can pull in loosely related text and make the writer answer an unanswerable question (the claim check's "does it answer the question" is the guard; watch the unanswerable column). It costs tokens and time for questions that were fine. If the second context is worse, the first draft is kept only when the second refuses, not when it is merely worse; fix by comparing the two drafts' coverage if that turns out to matter.


## Stage 7 (login): who is asking

1. **What:** prove who the caller is, so the access rules (public / member with licenses / admin) have a real identity behind them.
2. **Here:** `python -m scripts.setup_users` creates three demo users (alice: member with Kubernetes and PostgreSQL licenses, bob: member with none, admin) in MongoDB with random passwords printed once; only peppered, salted scrypt hashes are stored (`src/auth.py`; the pepper is a server secret in `.env`, so the database alone is not enough to guess passwords offline). `POST /login` returns a JWT (HS256, 60 minutes) signed with `JWT_SECRET` from `.env`. The token holds only the user id: the role and licenses are read from the database on every request, so a revoked license or deleted user stops working at once. No token means the public role; a bad or expired token is a 401, never a silent downgrade. Five wrong passwords lock a user out for a minute.
3. **Why:** without identity the "member sees internal docs of licensed products" rule is just a parameter anyone could set. Keeping secrets in `.env` keeps them out of git.
4. **Measure:** tests in `tests/test_entry.py`: wrong user and wrong password give the same answer, lockout, expired / tampered / orphaned tokens are 401, a license revoked after login applies to the next request, the principal passed to the pipeline is the token's user.
5. **Wrong:** a leaked `JWT_SECRET` lets anyone forge any user, and a token cannot be revoked before it expires (only the user's role and licenses are live). The lockout is in memory and per user name. No HTTPS here. Fix for a real deployment: a secret manager, short tokens plus refresh, HTTPS, a shared rate limiter. The users and the access levels are simulated.

## Stage 7 (web app and admin): sign in, ask, see the evidence, manage licenses

1. **What:** the screens people actually use: sign in, ask a question and see which passages the answer came from, browse the documents you may read, read the evaluation numbers, and (admins) give or take product licenses.
2. **Here:** a Next.js app in `web/` talks to the FastAPI API. Next.js keeps the login token in an `httpOnly` cookie and adds it to API calls, so page scripts never hold it. Users, licenses and the audit log are in MongoDB. The Ask screen draws every passage the writer saw as a tick (cited ones tall and blue) next to the answer; hovering a citation lights up its source and passage. The Evaluation screen is read from `eval/results/` by `/metrics`; Documents from `chunks.jsonl` filtered by the same access rule as search; the admin screen calls `/admin/*`.
3. **Why:** an access model nobody can see or change is hard to trust. Showing the evidence next to the answer lets a person check a claim in one click, and showing locked-page counts explains why "No documented fix found" can be true for one account and not another.
4. **Measure:** Python tests for the store (mongomock), admin-only routes, password hashing and pepper, documents per role and metrics against the result files (`tests/test_access.py`, `tests/test_entry.py`); `npm test` for the text sanitiser; the design inspector at three widths; and a real browser run: sign in, switch a license (persisted in MongoDB and audited), ask a question, open a citation.
5. **Wrong:** a password handed to a new user travels through the admin's browser; a cookie token is not revoked until it expires; the lockout is in memory; no HTTPS or encryption at rest here; the page does not show progress inside the 5-30 s wait because the API does not stream stages. Fix for real use: HTTPS, forced password change on first login, a shared rate limiter, token revocation list, streaming progress from the API.

## Stage 7 (input safety): length limit and prompt-injection check

1. **What:** refuse questions that are empty, too long, or that try to change the assistant's instructions or reach data it must not share, before any search or LLM call.
2. **Here:** `src/guard.py`: a 1,000-character limit, and a list of named regex rules (override instructions, reveal the prompt, change role, chat-markup tokens, ask for server secrets, bypass access, encoded payloads) on text that is first normalised (Unicode, zero-width characters, spaced-out letters). The same idea with a narrower rule set scans every retrieved chunk, and a chunk that looks like injected instructions is left out of the context. The writer prompt still calls excerpts data and the output checks still run.
3. **Why:** a blocked attack costs no tokens and cannot reach the writer; a poisoned document is the more realistic attack, because users cannot edit the docs but documents can carry text from outside.
4. **Measure:** `python -m eval.safety` on 20 fake attacks and 20 normal questions (`eval/safety_prompts.json`), the chunk scanner on 4 poisoned chunks and on all 2,602 real chunks, and (`--live`) the real writer on a poisoned context. First run: 14 of 20 attacks blocked and 3 of 20 normal questions wrongly blocked; after fixing the rules on those same prompts: 20 of 20 and 0 of 20 (an optimistic number, see the README). Real chunks flagged: 0 of 2,602. The live writer did not obey either poisoned chunk.
5. **Wrong:** rules miss paraphrases and other languages, and block honest questions that use trigger words ("developer mode", "disable authentication", a pasted log starting with `system:`). A very long unbroken string looks like an encoded payload. Fix: log the rule that fired, add a case to the test set for every miss or false block, and keep the model-level defences (excerpts are data, output checks) because a rule list is never complete.

## Stage 7 (rewrite): follow-up questions and the product

1. **What:** turn "and how do I do that on Kafka?" into a question that makes sense alone, and work out which product(s) the question is about.
2. **Here:** with a chat history, one cached call to Groq `gpt-oss-20b` (its own token bucket) rewrites the last question to be standalone (`src/rewrite.py`); history is passed as data, trimmed to 3 turns, and the rewrite must pass the same input checks. If it fails, the question is used as typed. The product comes from the query plan (`src/query.py`, one cached call) and is shown to the user; it only restricts the search if `rewrite.route_product` is on, which it is not.
3. **Why:** search engines do not remember the earlier turns. The product label helps the user see what was understood.
4. **Measure:** unit tests with a fake LLM (no call without history, history bounded and marked as data, failure keeps the question). The rewrite has no accuracy number: the test set has no multi-turn questions. Routing was 26 of 26 on the tuning questions with Groq (README, Query understanding), but turning it on as a filter was not measured on accuracy.
5. **Wrong:** a rewrite can drift from what the user meant or add a product they did not mention; a wrong single-product guess would hide the right docs if used as a filter, which is why it is off. Fix: keep the original question as one of the searches, measure with a multi-turn test set before enabling the filter.
