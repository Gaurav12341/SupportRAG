"""Stages 1-4 (offline): parse, clean, chunk, metadata. Run with `python -m src.ingest`."""
import json
from pathlib import Path

import yaml

from .chunk import chunk_text, load_tokenizer
from .clean import MASK_TYPES, clean_pages
from .metadata import add_metadata, load_access_rules
from .parse import parse_all

ROOT = Path(__file__).resolve().parent.parent.parent


def run():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf8"))
    sources = yaml.safe_load((ROOT / "configs" / "sources.yaml").read_text(encoding="utf8"))
    out_dir = ROOT / cfg["paths"]["processed"]
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {}

    # 1. parse
    parsed = parse_all(sources, cfg["ingest"]["min_chars"], stats)
    pages = []
    for source, items in parsed.items():
        for p in items:
            pages.append({**p, "source": source})
    stats["pages_parsed"] = {s: len(v) for s, v in parsed.items()}

    # 2. clean, dedupe, mask
    pages, clean_stats = clean_pages(pages)
    stats.update(clean_stats)
    stats["pages_kept"] = {s: sum(p["source"] == s for p in pages) for s in parsed}

    # 3 + 4. chunk, then attach metadata
    rules = load_access_rules()
    tok = load_tokenizer(cfg["models"]["embedding"])
    size, overlap = cfg["chunking"]["size_tokens"], cfg["chunking"]["overlap_tokens"]
    chunks = []
    for p in pages:
        meta = add_metadata(p, rules)
        for i, c in enumerate(chunk_text(p["text"], tok, size, overlap)):
            chunks.append({"chunk_id": f"{p['source_path']}#{i}", "chunk_index": i, **meta, **c, "text": c["text"]})
    stats["chunks"] = len(chunks)
    stats["chunks_by_source"] = {s: sum(c["source"] == s for c in chunks) for s in parsed}
    stats["chunks_by_access"] = {lv: sum(c["access_level"] == lv for c in chunks) for lv in ("public", "internal", "restricted")}
    stats["chunks_by_doc_type"] = {}
    for c in chunks:
        stats["chunks_by_doc_type"][c["doc_type"]] = stats["chunks_by_doc_type"].get(c["doc_type"], 0) + 1
    stats["chunk_settings"] = {"size_tokens": size, "overlap_tokens": overlap}

    with open(out_dir / "pages.jsonl", "w", encoding="utf8") as f:
        for p in pages:
            f.write(json.dumps({k: v for k, v in p.items()}, ensure_ascii=False) + "\n")
    with open(out_dir / "chunks.jsonl", "w", encoding="utf8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out_dir / "ingest_report.json").write_text(json.dumps(stats, indent=2), encoding="utf8")
    return stats


def print_summary(stats):
    print("\nPages per source (after dedupe):")
    for s, n in stats["pages_kept"].items():
        extra = []
        if stats["duplicates_dropped"].get(s):
            extra.append(f"{stats['duplicates_dropped'][s]} duplicates dropped")
        if stats["dropped_short"].get(s):
            extra.append(f"{stats['dropped_short'][s]} too short, skipped")
        print(f"  {s:14s} {n:4d}" + (f"   ({', '.join(extra)})" if extra else ""))
    print(f"  {'total':14s} {sum(stats['pages_kept'].values()):4d}")
    print(f"\nChunks: {stats['chunks']}  (size {stats['chunk_settings']['size_tokens']} tokens, "
          f"overlap {stats['chunk_settings']['overlap_tokens']})")
    for s, n in stats["chunks_by_source"].items():
        print(f"  {s:14s} {n:5d}")
    print("  access levels (simulated):", stats["chunks_by_access"])
    total = sum(stats["masked"].values())
    print(f"\nSecrets/personal data masked: {total}")
    for k in MASK_TYPES:
        if stats["masked"].get(k):
            print(f"  {k:14s} {stats['masked'][k]}")
