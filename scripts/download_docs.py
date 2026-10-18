"""Download the small doc set into data/raw/ (stage 0, before ingest).

Kubernetes, GitHub Docs and Kafka come from their public git repos (sparse/shallow clone).
PostgreSQL is fetched as HTML from postgresql.org. Stack Overflow Q&A comes from the
official Stack Exchange API (no key, CC BY-SA 4.0). Safe to re-run: existing files are kept.

    python -m scripts.download_docs
"""
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = "SupportRAG-learning/0.1 (personal portfolio project)"
PG_BASE = "https://www.postgresql.org/docs/current/"

REPOS = {
    "k8s_repo": ("https://github.com/kubernetes/website.git", ["content/en/docs/concepts", "content/en/docs/tasks"]),
    "gh_repo": ("https://github.com/github/docs.git", ["content/actions"]),
    "kafka_repo": ("https://github.com/apache/kafka-site.git", None),
}
SO_TAGS = {"kubernetes": "kubernetes", "postgres": "postgresql", "kafka": "apache-kafka", "github": "github-actions"}


def sh(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def clone_repos():
    for name, (url, sparse) in REPOS.items():
        dest = RAW / name
        if dest.exists():
            continue
        if sparse:
            sh("git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", url, str(dest))
            sh("git", "sparse-checkout", "set", *sparse, cwd=dest)
        else:
            sh("git", "clone", "--depth", "1", url, str(dest))


def download_postgres(chapters):
    out = RAW / "postgres"
    out.mkdir(parents=True, exist_ok=True)
    for ch in chapters:
        page = ch["page"]
        html = _cached(out, page)
        # sub-sections are same-directory links like "auth-pg-hba-conf.html"
        subs = []
        toc = re.search(r'<div class="toc">.*?</div>', html, re.S)  # only the chapter's own table of contents
        for href in re.findall(r'href="([^"#?]+\.html)"', toc.group(0) if toc else ""):
            if "/" not in href and href != page and href not in subs:
                subs.append(href)
        if page == "errcodes-appendix.html":
            subs = []
        for href in subs[: ch["max"] - 1]:
            _cached(out, href)


def _cached(out, name):
    f = out / name
    if not f.exists():
        f.write_bytes(get(PG_BASE + name))
        time.sleep(0.4)  # be polite
    return f.read_text(encoding="utf8")


def download_stackoverflow(n_per_tag=50):
    out = RAW / "stackoverflow"
    out.mkdir(parents=True, exist_ok=True)
    api = "https://api.stackexchange.com/2.3/"
    for source, tag in SO_TAGS.items():
        dest = out / f"{tag}.json"
        if dest.exists():
            continue
        q = (f"{api}search/advanced?order=desc&sort=votes&accepted=True&answers=1&q=error"
             f"&tagged={tag}&site=stackoverflow&pagesize={n_per_tag}&filter=withbody")
        items = json.loads(_gunzip(get(q)))["items"]
        ids = ";".join(str(i["accepted_answer_id"]) for i in items)
        time.sleep(1)
        answers = json.loads(_gunzip(get(f"{api}answers/{ids}?site=stackoverflow&filter=withbody&pagesize=100")))["items"]
        by_id = {a["answer_id"]: a for a in answers}
        rows = []
        for it in items:
            a = by_id.get(it["accepted_answer_id"])
            if a:  # keep only what we use; author names are dropped, the link is the attribution
                rows.append({"question_id": it["question_id"], "link": it["link"], "title": it["title"],
                             "tags": it["tags"], "question_html": it["body"], "answer_html": a["body"],
                             "license": it.get("content_license", "CC BY-SA 4.0"), "product": source})
        dest.write_text(json.dumps(rows, indent=1), encoding="utf8")
        print(f"stackoverflow {tag}: {len(rows)} Q&A")
        time.sleep(1)


def _gunzip(b):
    import gzip
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


if __name__ == "__main__":
    cfg = yaml.safe_load((ROOT / "configs" / "sources.yaml").read_text(encoding="utf8"))
    RAW.mkdir(parents=True, exist_ok=True)
    clone_repos()
    download_postgres(cfg["postgres"]["chapters"])
    download_stackoverflow()
    for name in REPOS:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAW / name, capture_output=True, text=True).stdout.strip()
        print(name, sha)
