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
