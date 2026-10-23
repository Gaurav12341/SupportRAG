"""The document library: which pages are in the corpus, and which of them a caller may read. Read from data/processed/chunks.jsonl once.

Access levels are SIMULATED on public docs. A caller sees the pages `Principal.allows()` lets them read, the same rule search uses;
for the pages they may NOT read they get only a count per product (titles of locked pages are not sent).
"""
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from src.access import ROOT


@lru_cache(maxsize=1)
def _pages(path):
    pages = {}
    for line in Path(path).open(encoding="utf8"):
        c = json.loads(line)
        p = pages.setdefault(c["source_path"], {"id": c["source_path"], "title": c["title"], "product": c["product"], "source": c["source"],
                                                "doc_type": c["doc_type"], "access_level": c["access_level"], "url": c["url"], "license": c["license"],
                                                "version": c["version"], "chunks": 0})
        p["chunks"] += 1
    return sorted(pages.values(), key=lambda p: (p["product"], p["title"].lower()))


def library(principal, cfg):
    """{documents: pages the caller may read, locked: {product: pages they may not}, totals: {product: all pages}}."""
    pages = _pages(str(ROOT / cfg["paths"]["processed"] / "chunks.jsonl"))
    allowed = [p for p in pages if principal.allows(p, cfg)]
    return {"documents": allowed,
            "locked": dict(Counter(p["product"] for p in pages if not principal.allows(p, cfg))),
            "totals": dict(Counter(p["product"] for p in pages)),
            "chunks": sum(p["chunks"] for p in allowed)}
