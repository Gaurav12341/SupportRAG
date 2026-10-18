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
4. **Measure:** chunk count, token sizes (max 500). Later: retrieval hit rate in the eval.
5. **Wrong:** cuts fall mid-sentence or between a command and its explanation. Fix later: split on headings.

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
