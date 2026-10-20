"""Stage 14 (output side): block secrets / personal data, warn on destructive commands, never cite what the caller
may not read. Reuses the ingest masker, so the answer is held to the same rules as the corpus."""
import re

from src.ingest.clean import mask


def find_sensitive(text):
    """{type: count} of secrets / personal data found in `text` (empty = clean)."""
    return mask(text)[1]


def dangerous_warnings(text, cfg):
    """Warnings (one per matching rule) for destructive commands in `text`."""
    return [r["warning"] for r in cfg["safety"]["dangerous_commands"] if re.search(r["pattern"], text, re.I)]


def readable_only(chunk_ids, by_id, principal, cfg):
    """Keep only chunk ids that are in the context AND that the principal may read."""
    return [c for c in chunk_ids if c in by_id and principal.allows(by_id[c], cfg)]
