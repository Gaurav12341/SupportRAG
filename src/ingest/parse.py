"""Stage 1: parse docs into clean text (markdown) that keeps headings, code blocks and tables."""
import json
import re
from pathlib import Path

import yaml
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parent.parent.parent

# GitHub Docs variables we can resolve by hand; any other {% data ... %} is dropped.
GH_VARS = {
    "prodname_actions": "GitHub Actions", "prodname_dotcom": "GitHub", "product_name": "GitHub",
    "prodname_copilot": "GitHub Copilot", "prodname_ghe_server": "GitHub Enterprise Server",
    "prodname_ghe_cloud": "GitHub Enterprise Cloud", "prodname_github_runner": "GitHub-hosted runner",
    "prodname_codeql": "CodeQL", "prodname_dependabot": "Dependabot", "prodname_pages": "GitHub Pages",
}
ADMON = {"note": "Note", "caution": "Caution", "warning": "Warning", "tip": "Tip", "important": "Important"}


# ---------- HTML -> markdown (PostgreSQL pages, Stack Overflow bodies, HTML tables inside md) ----------

def html_to_md(html, flat_headings=False):
    """flat_headings: render headings as bold lines (Stack Overflow posts must not outrank our own headings)."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "noscript"]):
        t.decompose()
    out = _tidy(_node(soup))
    if flat_headings:
        out = re.sub(r"^#{1,6} (.+)$", r"**\1**", out, flags=re.M)
    return out


def _tidy(s):
    s = re.sub(r"[ \t ]+\n", "\n", s)
    s = re.sub(r"(?<!\*)\*{4}(?!\*)", "", s)  # empty bold left by empty tags
    return re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"


def _text(node):
    return re.sub(r"\s+", " ", node.get_text()).strip()


def _node(n):
    if isinstance(n, NavigableString):
        if n.parent.name == "pre":
            return str(n)
        return "" if type(n).__name__ == "Comment" else re.sub(r"\s+", " ", str(n))
    name = n.name
    inner = lambda: "".join(_node(c) for c in n.children)  # noqa: E731
    if name and re.fullmatch(r"h[1-6]", name):
        return f"\n\n{'#' * int(name[1])} {_text(n)}\n\n"
    if name == "pre":
        return f"\n\n```\n{n.get_text().strip(chr(10))}\n```\n\n"
    if name == "code":
        return f"`{n.get_text()}`" if n.parent.name != "pre" else n.get_text()
    if name in ("strong", "b"):
        return f"**{inner().strip()}**"
    if name in ("em", "i"):
        return f"*{inner().strip()}*"
    if name == "br":
        return "\n"
    if name in ("ul", "ol"):
        items = []
        for k, li in enumerate(n.find_all("li", recursive=False), 1):
            body = _tidy(_node(li)).strip().replace("\n", "\n  ")
            items.append(f"{k}. {body}" if name == "ol" else f"- {body}")
        return "\n\n" + "\n".join(items) + "\n\n"
    if name == "dt":
        return f"\n\n**{_text(n).removesuffix(' #')}**\n"
    if name == "table":
        return _table(n)
    if name in ("p", "blockquote"):
        return f"\n\n{inner().strip()}\n\n"
    if name in ("dd", "div", "section", "dl", "tr"):
        return f"\n{inner()}\n"
    if name == "img":
        return ""
    return inner()


def _table(t):
    rows = [[re.sub(r"\s+", " ", c.get_text()).strip().replace("|", "\\|") for c in tr.find_all(["th", "td"])]
            for tr in t.find_all("tr")]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n\n" + "\n".join(lines) + "\n\n"


# ---------- markdown dialects (Hugo for Kubernetes/Kafka, Liquid for GitHub Docs) ----------

def split_front_matter(raw):
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", raw, re.S)
    if not m:
        return {}, raw
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        fm = fm if isinstance(fm, dict) else {}
    except yaml.YAMLError:
        fm = {}
        t = re.search(r"^title:\s*(.+)$", m.group(1), re.M)
        if t:
            fm["title"] = t.group(1).strip("'\" ")
    return fm, raw[m.end():]


def md_to_text(body):
    s = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    # HTML tables embedded in markdown (Kafka) -> markdown tables
    s = re.sub(r"<table.*?</table>", lambda m: "\n\n" + html_to_md(m.group(0)) + "\n", s, flags=re.S | re.I)
    # GitHub Liquid: resolve a few variables, drop the rest
    s = re.sub(r"\{%-?\s*data\s+variables\.[\w.]*?(\w+)\s*-?%\}", lambda m: GH_VARS.get(m.group(1), ""), s)
    s = re.sub(r"\{%-?.*?-?%\}", "", s, flags=re.S)
    s = re.sub(r"^>\s*\[!(\w+)\]\s*", lambda m: f"> **{m.group(1).title()}:** ", s, flags=re.M)
    # Hugo shortcodes
    s = re.sub(r"\{\{<?\s*/?\s*(note|caution|warning|tip|important)\s*>?\}\}",
               lambda m: "" if "/" in m.group(0) else f"**{ADMON[m.group(1)]}:** ", s)
    s = re.sub(r"\{\{<?\s*(?:glossary_tooltip|glossary_definition)[^>}]*?(?:text|term_id)=\"([^\"]+)\"[^>}]*>?\}\}", r"\1", s)
    s = re.sub(r"\{\{<?\s*feature-state([^>}]*)>?\}\}", lambda m: "Feature state: " + " ".join(
        re.findall(r"(?:for_k8s_version|state)=\"([^\"]+)\"", m.group(1))), s)
    s = re.sub(r"\{\{<?\s*tab\s+[^>}]*?name=\"([^\"]+)\"[^>}]*>?\}\}", r"**\1:**", s)
    s = re.sub(r"\{\{[<%].*?[>%]\}\}", "", s, flags=re.S)
    # markdown links/images -> text; headings, code fences and tables stay as they are
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))*(?:\s+\"[^\"]*\")?\)", r"\1", s)
    s = re.sub(r"</?(?:span|a|br|p|div|b|i|em|strong|sup|sub|center)\b[^>]*>", "", s, flags=re.I)
    s = re.sub(r"</?code>", "`", s, flags=re.I)
    return _tidy(s)


# ---------- per-source page lists ----------

def _url(product, rel):
    stem = re.sub(r"\.md$", "", rel)
    stem = re.sub(r"(^|/)_?index$", "", stem)
    return {
        "kubernetes": f"https://kubernetes.io/docs/{stem}/",
        "github": f"https://docs.github.com/en/actions/{stem}",
        "kafka": f"https://kafka.apache.org/43/{stem}/",
    }[product]


def _candidates(root, prefix):
    base = root / prefix
    if base.is_file():
        return [base]
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def parse_markdown_source(product, cfg, min_chars, stats):
    root = ROOT / cfg["root"]
    seen, pages = set(), []
    for rule in cfg["rules"]:
        taken = 0
        for p in _candidates(root, rule["prefix"]):
            if taken >= rule["max"]:
                break
            if p in seen:
                continue
            seen.add(p)
            fm, body = split_front_matter(p.read_text(encoding="utf8"))
            text = md_to_text(body)
            if len(text) < min_chars:
                stats["dropped_short"][product] = stats["dropped_short"].get(product, 0) + 1
                continue
            rel = p.relative_to(root).as_posix()
            title = str(fm.get("title") or rel)
            pages.append({
                "product": product, "version": cfg.get("version", "latest"),
                "source_path": f"{product}/{rel}", "url": _url(product, rel), "title": title,
                "native_type": str(fm.get("content_type") or fm.get("contentType") or ""),
                "license": cfg["license"], "text": f"# {title}\n\n{text}",
            })
            taken += 1
    return pages


def parse_postgres(cfg, min_chars, stats):
    root = ROOT / cfg["root"]
    pages, seen = [], set()
    for ch in cfg["chapters"]:
        page = ch["page"]
        html = (root / page).read_text(encoding="utf8")
        toc = re.search(r'<div class="toc">.*?</div>', html, re.S)
        names = [page]
        if page != "errcodes-appendix.html":
            names += [h for h in dict.fromkeys(re.findall(r'href="([^"#?/]+\.html)"', toc.group(0) if toc else "")) if h != page]
        taken = 0
        for name in names:
            if taken >= ch["max"] or name in seen or not (root / name).exists():
                continue
            seen.add(name)
            soup = BeautifulSoup((root / name).read_text(encoding="utf8"), "html.parser")
            main = soup.find(id="docContent")
            if main is None:
                continue
            for junk in main.select(".navheader, .navfooter, .docs-version, .docComments"):
                junk.decompose()
            head = main.find(["h1", "h2"])
            title = re.sub(r"\s*#$", "", _text(head)) if head else name
            text = html_to_md(str(main))
            text = re.sub(r"^(#{1,6} .*?) #$", r"\1", text, flags=re.M)  # drop the "#" permalink anchor
            text = re.sub(r"^#{1,6} (Note|Warning|Tip|Caution|Important)$", r"**\1:**", text, flags=re.M)
            first = text.split("\n", 1)
            if re.sub(r"^#+ ", "", first[0]) == title:  # the page's own heading becomes the title line
                text = f"# {title}\n{first[1] if len(first) > 1 else ''}"
            else:
                text = f"# {title}\n\n{text}"
            if len(text) < min_chars:
                stats["dropped_short"]["postgres"] = stats["dropped_short"].get("postgres", 0) + 1
                continue
            pages.append({
                "product": "postgres", "version": str(cfg["version"]), "source_path": f"postgres/{name}",
                "url": "https://www.postgresql.org/docs/current/" + name, "title": title,
                "native_type": "reference" if name.startswith(("runtime-config", "errcodes")) else "",
                "license": cfg["license"], "text": text,
            })
            taken += 1
    return pages


def parse_stackoverflow():
    pages = []
    for f in sorted((ROOT / "data" / "raw" / "stackoverflow").glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf8")):
            q = html_to_md(r["question_html"], flat_headings=True)
            a = html_to_md(r["answer_html"], flat_headings=True)
            pages.append({
                "product": r["product"], "version": "n/a", "source_path": f"stackoverflow/{r['question_id']}",
                "url": r["link"], "title": r["title"], "native_type": "qa", "license": r["license"],
                "text": f"# {r['title']}\n\n## Question\n\n{q}\n\n## Accepted answer\n\n{a}",
            })
    return pages


def parse_all(cfg, min_chars, stats):
    stats.setdefault("dropped_short", {})
    return {
        "kubernetes": parse_markdown_source("kubernetes", cfg["kubernetes"], min_chars, stats),
        "github": parse_markdown_source("github", cfg["github"], min_chars, stats),
        "kafka": parse_markdown_source("kafka", cfg["kafka"], min_chars, stats),
        "postgres": parse_postgres(cfg["postgres"], min_chars, stats),
        "stackoverflow": parse_stackoverflow(),
    }
