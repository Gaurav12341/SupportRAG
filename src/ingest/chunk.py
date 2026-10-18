"""Stage 3: fixed-size chunks (about 500 tokens) with a small overlap. The simple version.

Tokens are counted with the embedding model's own tokenizer, so a chunk is never
longer than the model can read. Chunk boundaries ignore headings and sentences on purpose;
smarter splitting comes later.
"""
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
