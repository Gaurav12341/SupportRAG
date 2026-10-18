"""Stage 2: remove leftover menus/footers, drop exact duplicate pages, mask secrets and personal data."""
import hashlib
import re

# Lines that are navigation or footer boilerplate, not content.
BOILERPLATE = [
    r"^\s*(prev|previous)\s*\|?\s*(up)?\s*\|?\s*(next)?\s*$",
    r"^\s*(home|up|next|prev|previous)(\s+(home|up|next|prev|previous))*\s*$",
    r"^\s*submit correction\b.*$",
    r"^\s*if you see anything in the documentation that is not correct.*$",
    r"^\s*(was this page helpful|was this helpful)\??.*$",
    r"^\s*(edit this page|create an issue|print entire section|report a problem).*$",
    r"^\s*copyright\s+(©|\(c\))?\s*\d{4}.*$",
    r"^\s*(skip to (main )?content|table of contents|on this page)\s*$",
    r"^\s*privacy policy\s*\|.*$",
]
BOILERPLATE_RE = [re.compile(p, re.I) for p in BOILERPLATE]

# Safe values we keep on purpose.
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "localhost", "test.com", "users.noreply.github.com")
PLACEHOLDER_RE = re.compile(r"example|x{4,}|\*{4,}|0{6,}|<[^>]+>|\$\{|\$\w|\{\{|your[_-]|changeme|placeholder|redacted", re.I)

# the last domain label must be letters, so "action@v3.0.0" (a git ref) is not an email;
# a leading "$" means a shell variable in a URL ($TOKEN@github.com), not an address
EMAIL_RE = re.compile(r"(?<![\w.%+$-])[\w.%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}|localhost)\b")
PHONE_RE = re.compile(
    r"(?<![\w.:/@%-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{3,4}(?![\w.@%-])")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)

# Known token shapes -> label
TOKEN_PATTERNS = [
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("API_KEY", re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bgsk_[A-Za-z0-9]{20,}\b|\bsk-[A-Za-z0-9]{32,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("BEARER_TOKEN", re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{20,})")),
]
# key = value style assignments: mask the value when it looks random (letters + digits, 12+ chars)
ASSIGN_RE = re.compile(
    r"(?i)\b((?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|token|password|passwd|pwd)\s*[:=]\s*[\"']?)"
    r"([A-Za-z0-9/+=_.-]{12,})")

MASK_TYPES = ["EMAIL", "PHONE", "PRIVATE_KEY", "AWS_KEY", "GITHUB_TOKEN", "SLACK_TOKEN", "API_KEY",
              "JWT", "BEARER_TOKEN", "SECRET"]


def _looks_random(v):
    return bool(re.search(r"[A-Za-z]", v) and re.search(r"\d", v)) and not PLACEHOLDER_RE.search(v)


def mask(text):
    """Return (masked_text, {type: count}). Placeholders and safe domains are kept."""
    counts = {}

    def hit(kind):
        counts[kind] = counts.get(kind, 0) + 1
        return f"[MASKED_{kind}]"

    text = PRIVATE_KEY_RE.sub(lambda m: hit("PRIVATE_KEY"), text)
    for kind, rx in TOKEN_PATTERNS:
        if kind == "BEARER_TOKEN":
            text = rx.sub(lambda m: m.group(1) + hit(kind) if _looks_random(m.group(2)) else m.group(0), text)
        else:
            text = rx.sub(lambda m, k=kind: m.group(0) if PLACEHOLDER_RE.search(m.group(0)) else hit(k), text)
    text = ASSIGN_RE.sub(lambda m: m.group(1) + hit("SECRET") if _looks_random(m.group(2)) else m.group(0), text)

    def email(m):
        domain = m.group(1).lower()
        return m.group(0) if domain.endswith(SAFE_EMAIL_DOMAINS) else hit("EMAIL")

    text = EMAIL_RE.sub(email, text)
    text = PHONE_RE.sub(lambda m: hit("PHONE"), text)
    return text, counts


def strip_boilerplate(text):
    lines = [ln for ln in text.split("\n") if not any(rx.match(ln) for rx in BOILERPLATE_RE)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def fingerprint(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode("utf8")).hexdigest()


def clean_pages(pages):
    """pages: list of dicts with 'text'. Returns (kept_pages, stats)."""
    seen, kept = {}, []
    stats = {"duplicates_dropped": {}, "masked": {}, "masked_by_source": {}}
    for p in pages:
        text = strip_boilerplate(p["text"])
        fp = fingerprint(text)
        if fp in seen:
            src = p["source"]
            stats["duplicates_dropped"][src] = stats["duplicates_dropped"].get(src, 0) + 1
            stats.setdefault("duplicate_pairs", []).append([p["source_path"], seen[fp]])
            continue
        seen[fp] = p["source_path"]
        text, counts = mask(text)
        for k, v in counts.items():
            stats["masked"][k] = stats["masked"].get(k, 0) + v
            by = stats["masked_by_source"].setdefault(p["source"], {})
            by[k] = by.get(k, 0) + v
        kept.append({**p, "text": text, "masked": counts})
    return kept, stats
