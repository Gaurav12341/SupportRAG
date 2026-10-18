# DATA SOURCES

Public data only. Downloaded by `scripts/download_docs.py` into `data/raw/` (git-ignored).
Which pages are used is set in `configs/sources.yaml`. Checked 2026-10-18.

| Source | Where from | Version | License | Pages used |
|--------|-----------|---------|---------|-----------|
| Kubernetes docs | github.com/kubernetes/website (commit `91896e2`), `content/en/docs` | v1.37 (main branch) | CC BY 4.0 (repo `LICENSE`) | 100 |
| GitHub Docs (Actions) | github.com/github/docs (commit `dae83f7`), `content/actions` | github.com, main branch | CC BY 4.0 for docs content; MIT for code (repo `LICENSE`, `LICENSE-CODE`) | 94 |
| Kafka docs | github.com/apache/kafka-site (commit `e6cbeb5`), `content/en/43` | 4.3 | Apache License 2.0 (repo `LICENSE`) | 65 |
| PostgreSQL docs | postgresql.org/docs/current (HTML) | 18 | PostgreSQL License (postgresql.org/about/licence) | 78 |
| Stack Overflow Q&A | official Stack Exchange API v2.3 (no key) | n/a | CC BY-SA 4.0 (returned in each item's `content_license`) | 200 (50 each: kubernetes, postgresql, apache-kafka, github-actions) |

## Notes

- **Stack Overflow:** an easy and allowed way exists, so it is included. The API is public, and the
  content is CC BY-SA 4.0, which requires attribution and share-alike. We keep each question's
  `url` and license in every chunk's metadata so answers can link back. Author names are dropped.
  Selection: accepted answer exists, tag match, text matches "error", sorted by votes, top 50 per tag.
  The API allows about 300 requests a day without a key; we used 8.
- **Kafka has only 65 pages with real content** in the 4.3 docs (the rest are stubs or generated
  config tables), so it is under the ~100 target. Not padded with older versions.
- **GitHub Docs** are Liquid templates. A few variables (`{% data variables.product.prodname_actions %}`)
  are resolved by hand; other `{% ... %}` tags are dropped, and `ifversion` blocks keep all branches.
- **Kubernetes/GitHub/Kafka repos are cloned** (shallow, sparse where possible), not scraped.
  PostgreSQL pages were fetched politely (0.4 s between requests, one user agent).
- Attribution lines and licenses must go in the README before this project is shared publicly.
