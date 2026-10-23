# INTERVIEW cheat sheet: SupportRAG on one page

**The pitch:** ask about an error, get steps that cite the docs (Kubernetes, PostgreSQL, Kafka, GitHub Actions); if the docs have no fix it says "No documented fix found" instead of guessing. Built on free tools and a 4 GB GPU. Final holdout accuracy **78.9%** (30/38, 95% CI 63.7-88.9%), all 12 unanswerable questions refused. Access levels and users are simulated on public docs.

One sentence per stage: *what it does* / **the biggest thing that goes wrong** (details in `docs/LEARNING.md`).

| # | Stage | What it does / what goes wrong |
|---|---|---|
| 1 | Parse | Turns markdown, HTML and JSON into plain text that keeps headings, code and tables. / **Template leftovers or lost tables silently corrupt the text.** |
| 2 | Clean, dedupe, mask | Removes menus and duplicate pages and hides emails, phones and keys. / **A masking regex fires on harmless text (`action@v3.0.0` looked like an email) or misses a real secret.** |
| 3 | Chunk | Cuts pages into ~500-token windows. / **Cuts fall between a command and its explanation; heading-aware splitting looked tidier but did not retrieve better.** |
| 4 | Metadata + access level | Tags each chunk with product, URL, license and a simulated access level. / **A page lands in the wrong level; the fix is a rules file, not code.** |
| 5 | Embed | Turns chunks into 384 numbers (bge-small) so similar meaning is close. / **Exact strings like error codes match loosely, which is why BM25 is added.** |
| 6 | Store (Qdrant) | Keeps vectors plus metadata and finds nearest ones fast. / **Mixing vectors from two models gives nonsense, so the collection records the model name and refuses a mismatch.** |
| 7a | Login | Salted-scrypt passwords and 60-minute JWTs; role and licenses are read from the database on every request. / **A leaked `JWT_SECRET` lets anyone forge a user, and a token cannot be revoked early.** |
| 7b | Input safety | A length limit and named injection rules on the question, plus a scan of retrieved chunks. / **Rules miss paraphrases and other languages and block honest questions with trigger words (14/20 attacks, 3/20 false blocks before I fixed them).** |
| 7c | Rewrite + product | Rewrites a follow-up into a standalone question and names the product. / **A rewrite can drift from the user's meaning; routing as a filter would hide the right docs when wrong, so it is off.** |
| 8-9 | Retrieve | Meaning search plus BM25, both filtered by what the caller may read before ranking. / **A post-filter would leak or return too few; recall for public users legitimately drops on licensed content.** |
| 10 | Merge (RRF) | Combines the two ranked lists by rank. / **One weak list can add noise, and small test sets cannot tell a one-rank gain from luck.** |
| 11 | Rerank | A cross-encoder re-scores the top 30. / **Slow on CPU and no measured gain, so it is off.** |
| 12 | Build context | Grows each chunk to its section, drops repeats, keeps 10 chunks / 12,000 characters. / **Huge sections or a missing neighbour chunk hide the evidence from the writer (a real bug I found and fixed).** |
| 13 | Generate | Groq `gpt-oss-120b` writes a JSON answer with a kind, coverage, summary and cited points; local Qwen is the failsafe. / **A small model invents advice, cites the wrong excerpt or obeys text inside an excerpt; the 3B local model scored 30-37%.** |
| 14 | Verify + output safety | One `gpt-oss-20b` call marks each point supported or not and whether the question is answered; secrets are masked and risky commands get warnings. / **The checker can let a wrong claim through (2 shown answers on the holdout were judged wrong).** |
| 15 | Evaluate | Judge-graded accuracy (correct + correctly refused) with Wilson intervals and a failure breakdown. / **A model grading with a model's labels flatters itself, and 38 questions mean one question is 2.6 points.** |
| 16 | Retry loop | Searches again with a query plan and the writer's own "missing" text when coverage is partial. / **It did not help (80.0% vs 82.5% dev) and can pull in loosely related text, so it is off.** |

**Numbers to know:** baseline 30% (local 3B writer) -> 45% with a strong writer but the old NLI verifier -> 82.5% on the dev subset with the LLM claim check -> **78.9% on the untouched holdout**. Weakest type: cross-product (0/5 on the holdout). Free tier: about 55 answers a day on the 120b model.

**Questions to be ready for:** why a 120b API model instead of local (the 3B model was too weak, measured); why LLM-as-judge and how it was checked (29/30 agreement with hand labels, a different model family, still an LLM); what I tried that did not work (reranker, bge-m3, heading chunks, HyDE, retry loop, all measured and left off); what I would do for production (human-written test set from real tickets, paid tier or hosted open model, real identity provider, HTTPS, monitoring).
