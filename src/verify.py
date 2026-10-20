"""Stage 14 (verify): is every step backed by the text it cites?

1. Every cited id must be one of the chunks we actually put in the context (anything else is invented, or may be
   a chunk the caller is not allowed to see).
2. A step copied from the cited text (at least `min_copied_trigrams` of its word triples appear there) is supported
   as it is: the NLI model scores near-verbatim code, lists and tables at about 0, so it cannot be the only test.
3. Otherwise a small NLI model (config models.nli) scores "does the cited text entail this step?". The cited section is cut into
   windows that fit the model; the step's score is the best window. A step is supported at >= min_nli_entailment.
"""
import re
from functools import lru_cache

import numpy as np

WINDOW_CHARS = 1200  # NLI model reads at most 512 tokens (premise + step)


@lru_cache(maxsize=1)
def _nli(name, device):
    from sentence_transformers import CrossEncoder
    # models are pre-downloaded by scripts/download_models.py; stay offline
    return CrossEncoder(name, device=device, max_length=512, local_files_only=True)


def windows(text, size=WINDOW_CHARS):
    """Pack paragraphs (blank-line separated; code blocks stay whole) into windows of about `size` characters."""
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return [w[:size * 2] for w in out]


def entailment(pairs, cfg):
    """P(entailment) for each (premise, hypothesis). Label order comes from the model's own config."""
    if not pairs:
        return []
    m = _nli(cfg["models"]["nli"], cfg["models"]["device"])
    logits = np.asarray(m.predict(pairs, batch_size=16, show_progress_bar=False, apply_softmax=False))
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    ent = next(int(i) for i, name in m.model.config.id2label.items() if name.lower() == "entailment")
    return [float(p[ent]) for p in probs]


def step_support(step_text, cited_items, cfg):
    """Best entailment of `step_text` over all windows of the cited context items (0.0 if nothing is cited)."""
    pairs = [(w, step_text[:600]) for it in cited_items for w in windows(it["text"])]
    return max(entailment(pairs, cfg), default=0.0)


def copied_fraction(step_text, cited_items):
    """Share of the step's word triples that appear in one cited text (1.0 = copied word for word)."""
    words = lambda t: re.findall(r"[a-z0-9_.\-/]+", t.lower())
    grams = lambda w: {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
    mine = grams(words(step_text))
    return max((len(mine & grams(words(it["text"]))) / len(mine) for it in cited_items), default=0.0) if mine else 0.0
