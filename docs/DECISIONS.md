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
