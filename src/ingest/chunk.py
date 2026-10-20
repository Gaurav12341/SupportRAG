"""Stage 3: fixed-size chunks (about 500 tokens) with a small overlap. The simple version.

Tokens are counted with the embedding model's own tokenizer, so a chunk is never
longer than the model can read. Chunk boundaries ignore headings and sentences on purpose;
smarter splitting comes later.
"""
import re
from bisect import bisect_left

from transformers import AutoTokenizer


def load_tokenizer(model_name):
    # models are pre-downloaded by scripts/download_models.py; stay offline
    return AutoTokenizer.from_pretrained(model_name, local_files_only=True)


def chunk_text(text, tokenizer, size, overlap):
    """Split text into windows of `size` tokens, each starting `size - overlap` after the last."""
    assert 0 <= overlap < size
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                    truncation=False, verbose=False)
    offsets = enc["offset_mapping"]
    n = len(offsets)
    chunks, start = [], 0
    while n:
        end = min(start + size, n)
        piece = text[offsets[start][0]:offsets[end - 1][1]].strip()
        if piece:
            chunks.append({"text": piece, "n_tokens": end - start})
        if end == n:
            break
        start = end - overlap
    return chunks


# ---------- heading-aware chunks (config chunking.strategy: headings) ----------

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE = re.compile(r"^\s*(?:>\s*)*(```|~~~)")  # also fences inside a "> " blockquote


def split_blocks(text):
    """Split markdown into blocks: ('heading', line) | ('code', fenced block) | ('table', rows) | ('text', paragraph).
    Code blocks and tables are single blocks, so they are never cut at a blank line inside them."""
    blocks, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            j = i + 1
            while j < len(lines) and not FENCE.match(lines[j]):
                j += 1
            blocks.append(("code", "\n".join(lines[i:j + 1])))
            i = j + 1
        elif HEADING.match(line):
            blocks.append(("heading", line.strip()))
            i += 1
        elif line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append(("table", "\n".join(lines[i:j])))
            i = j
        elif line.strip():
            j = i
            while j < len(lines) and lines[j].strip() and not FENCE.match(lines[j]) \
                    and not HEADING.match(lines[j]) and not lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append(("text", "\n".join(lines[i:j])))
            i = j
        else:
            i += 1
    return blocks


def _n_tokens(tokenizer, text):
    return len(tokenizer(text, add_special_tokens=False, truncation=False, verbose=False)["input_ids"])


def _split_big(kind, block, tokenizer, size, overlap):
    """A single block larger than `size`: code and tables split on line boundaries (a table repeats its header
    rows), plain text falls back to the fixed token windows."""
    if kind == "text":
        return [c["text"] for c in chunk_text(block, tokenizer, size, overlap)]
    lines = block.split("\n")
    head = lines[:2] if kind == "table" else lines[:1]  # table header + separator / opening fence
    body = lines[len(head):] if kind == "table" else lines[1:]
    close = ["```"] if kind == "code" and body and FENCE.match(body[-1]) else []
    body = body[:-1] if close else body
    pieces, cur = [], []
    for ln in body:
        trial = "\n".join(head + cur + [ln] + close)
        if cur and _n_tokens(tokenizer, trial) > size:
            pieces.append("\n".join(head + cur + close))
            cur = []
        cur.append(ln)
    if cur:
        pieces.append("\n".join(head + cur + close))
    # a single huge line (minified code) cannot be split on lines: fall back to token windows
    return [w["text"] for p in pieces
            for w in (chunk_text(p, tokenizer, size, overlap) if _n_tokens(tokenizer, p) > size else [{"text": p}])]


def chunk_markdown(text, tokenizer, size, min_tokens=100):
    """Split at headings; a chunk never ends inside a code block or table unless that block alone exceeds `size`.
    Sections are packed greedily up to `size` tokens, but a new heading starts a new chunk once the current chunk has
    at least `min_tokens` (tiny sections are merged into their neighbour). A chunk that continues a section
    starts with that section's heading line again, so it is never cut off from its topic."""
    out, cur, cur_tok, heading = [], [], 0, ""

    def flush():
        nonlocal cur, cur_tok
        if any(not HEADING.match(b) for b in cur):  # a heading with nothing under it is not a chunk
            out.append({"text": "\n\n".join(cur).strip(), "n_tokens": cur_tok})
        cur, cur_tok = [], 0

    for kind, block in split_blocks(text):
        if kind == "heading":
            heading = block
            if cur_tok >= min_tokens:
                flush()
            cur.append(block)
            cur_tok += _n_tokens(tokenizer, block)
            continue
        n = _n_tokens(tokenizer, block)
        if n > size:  # oversized block: its own chunks, after whatever came before it
            flush()
            for piece in _split_big(kind, block, tokenizer, size - 20, 0 if kind != "text" else 50):
                body = piece if not heading or heading in piece else f"{heading}\n\n{piece}"
                out.append({"text": body, "n_tokens": _n_tokens(tokenizer, body)})
            continue
        if cur and cur_tok + n > size:
            flush()
            if heading and not block.startswith(heading):
                cur.append(heading)
                cur_tok = _n_tokens(tokenizer, heading)
        cur.append(block)
        cur_tok += n
    flush()
    return [c for c in out if c["text"]]


# ---------- recursive chunks (config chunking.strategy: recursive) ----------

SEPARATORS = ["\n# ", "\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " "]  # coarse to fine
_KEEP_WITH_NEXT = {"\n# ", "\n## ", "\n### ", "\n#### "}  # the newline ends the previous piece, the heading starts the next


def chunk_recursive(text, tokenizer, size, overlap=0):
    """Split at the coarsest separator that makes pieces fit: headings, then blank lines, lines, sentences, words.
    Neighbouring pieces are packed together up to `size` tokens. Every chunk is an exact slice of `text` (so it can be
    found in the page again), and a chunk starts `overlap` tokens early, at a piece boundary, so a sentence is not
    cut off from the one before it. Unlike chunk_markdown it does not know about code fences or tables."""
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False)
    starts = [o[0] for o in enc["offset_mapping"]]
    n = lambda a, b: bisect_left(starts, b) - bisect_left(starts, a)  # tokens in text[a:b]
    spans, cuts = [], set()

    def cut_points(a, b, sep):
        out, i = [], text.find(sep, a, b)
        while i != -1:
            c = i + 1 if sep in _KEEP_WITH_NEXT or sep == "\n\n" or sep == "\n" else i + len(sep)
            if a < c < b:
                out.append(c)
            i = text.find(sep, i + 1, b)
        return sorted(set(out))

    def split(a, b, level):
        if not text[a:b].strip():
            return
        if n(a, b) <= size:
            spans.append((a, b))
            return
        if level == len(SEPARATORS):  # nothing left to split on (e.g. one huge token run): hard windows
            lo = bisect_left(starts, a)
            for k in range(lo, bisect_left(starts, b), size):
                s = starts[k]
                e = starts[k + size] if k + size < len(starts) and starts[k + size] < b else b
                spans.append((s, e))
            return
        points = cut_points(a, b, SEPARATORS[level])
        if not points:
            return split(a, b, level + 1)
        cuts.update(points)
        bounds = [a] + points + [b]
        cur = None  # start of the span being packed
        for x, y in zip(bounds, bounds[1:]):
            if n(x, y) > size:  # this piece alone is too big: flush, then split it finer
                if cur is not None:
                    spans.append((cur, x))
                    cur = None
                split(x, y, level + 1)
            elif cur is None:
                cur = x
            elif n(cur, y) > size:
                spans.append((cur, x))
                cur = x
        if cur is not None:
            spans.append((cur, b))

    split(0, len(text), 0)
    spans.sort()
    ordered_cuts = sorted(cuts)
    out = []
    for i, (a, b) in enumerate(spans):
        if i and overlap:
            back = [c for c in ordered_cuts if c < a and n(c, a) <= overlap and n(c, b) <= size and c >= spans[i - 1][0]]
            a = back[0] if back else a
        piece = text[a:b].strip()
        if piece:
            out.append({"text": piece, "n_tokens": n(a, b)})
    return out
