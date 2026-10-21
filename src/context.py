"""Stage 12: build the context. Best chunks first, each expanded to its parent section, duplicates removed.

A "parent section" is the part of the page from the nearest heading at or above the chunk up to the next heading of
the same or a higher level. If that is longer than `context.max_section_chars`, the chunk itself (with its heading)
is used instead. All sections of one page share the page's access level, so expanding a chunk never shows more
than the caller may read; chunks the caller may not read are dropped anyway (defence in depth).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from src.access import Principal
from src.ingest.chunk import FENCE

ROOT = Path(__file__).resolve().parent.parent
HEADING = re.compile(r"^(#{1,6})\s+\S")


@lru_cache(maxsize=2)
def _pages(path):
    with open(path, encoding="utf8") as f:
        rows = (json.loads(line) for line in f)
        return {p["source_path"]: p["text"] for p in rows}


def load_pages(cfg):
    return _pages(str(ROOT / cfg["paths"]["processed"] / "pages.jsonl"))


def headings(text):
    """[(char position, level)] of markdown headings; '#' lines inside code fences are not headings."""
    out, pos, in_fence = [], 0, False
    for line in text.split("\n"):
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (m := HEADING.match(line)):
            out.append((pos, len(m.group(1))))
        pos += len(line) + 1
    return out


def heading_path(page_text, pos):
    """Titles of the headings above character `pos`, outermost first (a deeper heading replaces one of the same or lower level):
    ["Install", "Configure"] for a chunk under "## Configure" inside "# Install"."""
    path, in_fence = [], False
    for line in page_text[:pos].split("\n"):
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (m := HEADING.match(line)):
            level = len(m.group(1))
            path = [(lv, t) for lv, t in path if lv < level] + [(level, line[level:].strip())]
    return [t for _, t in path]


def parent_section(page_text, chunk_text, max_chars):
    """The section of `page_text` that contains the chunk, or the chunk itself if the section is too long
    or the chunk cannot be located. Returns (start, end, head): the span in the page, and a heading line to put in
    front when the span is the chunk alone (so it is not cut off from its topic); head is "" otherwise.
    start is -1 if the chunk is not in the page."""
    start = page_text.find(chunk_text)
    if start < 0:
        return -1, -1, ""
    end = start + len(chunk_text)
    hs = headings(page_text)
    above = [h for h in hs if h[0] <= start]
    sec_start, level = above[-1] if above else (0, 0)
    nxt = [p for p, lv in hs if p > sec_start and lv <= level] if level else []
    sec_end = max(nxt[0] if nxt else len(page_text), end)
    if sec_end - sec_start <= max_chars:
        return sec_start, sec_end, ""
    head = page_text[sec_start:page_text.find("\n", sec_start)].strip() if above else ""
    return start, end, "" if not head or head in chunk_text else head


def _render(page_text, start, end, head):
    body = page_text[start:end].strip()
    return f"{head}\n\n{body}" if head else body


def build_context(hits, principal=None, cfg=None, pages=None):
    """hits: search results, strongest first. Returns items, strongest first:
    {label S1.., chunk_id, chunk_ids (every retrieved chunk inside this text), source_path, title, url, product,
     access_level, text}.
    Spans of the same page that overlap or touch (neighbouring chunks overlap by design) are joined into one item
    holding the text of both, as long as the joined span stays under twice `max_section_chars`; otherwise the later
    hit is kept as its own item with the already-shown part cut off. Nothing a hit contributed is ever dropped
    except by the total `max_context_chars` budget, which cuts the weakest items first."""
    from src.llm import load_config
    cfg = cfg or load_config()
    principal = principal or Principal.public()
    pages = pages if pages is not None else load_pages(cfg)
    c = cfg["context"]
    items = []  # each also carries _span = (start, end, head) in its page, -1 if unknown
    for h in hits:
        if not principal.allows(h, cfg):
            continue
        page = pages.get(h["source_path"])
        start, end, head = parent_section(page, h["text"], c["max_section_chars"]) if page else (-1, -1, "")
        if start < 0:
            items.append(_item(h, h["text"], (-1, -1, ""), len(items)))
            continue
        near = next((it for it in items if it["source_path"] == h["source_path"] and it["_span"][0] >= 0
                     and start <= it["_span"][1] and it["_span"][0] <= end), None)
        if near is not None:
            s0, e0, h0 = near["_span"]
            if max(e0, end) - min(s0, start) <= 2 * c["max_section_chars"]:
                near["_span"] = (min(s0, start), max(e0, end), h0 or head)
                near["text"] = _render(page, *near["_span"])
                near["chunk_ids"].append(h["chunk_id"])
                continue
            start = max(start, e0) if start < e0 else start  # keep only the part not shown yet
            if start >= end:
                near["chunk_ids"].append(h["chunk_id"])
                continue
        items.append(_item(h, _render(page, start, end, head), (start, end, head), len(items)))
    budget = c["max_context_chars"]
    kept = []
    for it in items:  # strongest first; the first item is always kept (cut to fit)
        room = budget - sum(len(k["text"]) for k in kept)
        if room <= 0 or (kept and len(it["text"]) > room):
            continue
        it["text"] = it["text"][:room]
        kept.append(it)
    for i, it in enumerate(kept, 1):
        it["label"] = f"S{i}"
        it.pop("_span")
    return kept


def _item(h, text, span, n):
    return {"label": f"S{n + 1}", "chunk_id": h["chunk_id"], "chunk_ids": [h["chunk_id"]], "source_path": h["source_path"],
            "title": h["title"], "url": h["url"], "product": h["product"], "access_level": h["access_level"],
            "text": text, "_span": span}
