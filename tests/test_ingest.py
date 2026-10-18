"""Tests for stages 1-4. All secrets here are FAKE and built from fragments so scanners do not flag the file."""
import pytest

from src.ingest.chunk import chunk_text, load_tokenizer
from src.ingest.clean import clean_pages, mask, strip_boilerplate
from src.ingest.metadata import access_level, doc_type, load_access_rules
from src.ingest.parse import html_to_md, md_to_text

FAKE = {
    "AWS_KEY": "AKIA" + "ZZ9Y8X7W6V5U4T3S",
    "GITHUB_TOKEN": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "SLACK_TOKEN": "xoxb-" + "123456789012-abcdefghijkl",
    "API_KEY": "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
    "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.c2lnbmF0dXJlZmFrZQ",
}


@pytest.mark.parametrize("kind", list(FAKE))
def test_fake_secrets_are_masked(kind):
    out, counts = mask(f"use this: {FAKE[kind]} in the config")
    assert FAKE[kind] not in out
    assert counts == {kind: 1}


def test_private_key_and_assignment_and_bearer_masked():
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIFAKEFAKEFAKE\n-----END RSA PRIVATE KEY-----"
    out, counts = mask(key + "\npassword = Zx9Qw8Er7Ty6U5i4\nAuthorization: Bearer abcDEF123456ghiJKL789012mno")
    assert "MIIFAKE" not in out and "Zx9Qw8Er7Ty6U5i4" not in out and "abcDEF123456ghiJKL789012mno" not in out
    assert counts == {"PRIVATE_KEY": 1, "SECRET": 1, "BEARER_TOKEN": 1}


def test_email_and_phone_masked():
    out, counts = mask("mail jane.doe@acme-corp.io or call +1 555-123-4567 or (555) 123-4567")
    assert "jane.doe" not in out and "555-123-4567" not in out
    assert counts == {"EMAIL": 1, "PHONE": 2}


@pytest.mark.parametrize("safe", [
    "contact user@example.com", "curl http://localhost:8080/health", "host=127.0.0.1 port=5432",
    "ip 192.168.100.100 and 10.0.0.1", "version 1.2.3.4 released 2024-01-15 10:30:45",
    "key AKIAIOSFODNN7EXAMPLE", "token ghp_" + "x" * 36, "password: changeme", "token: ${TOKEN_VALUE_123}",
    "uses: octo-org/deploy-action@v3.0.0", "https://$GITHUB_TOKEN@github.com/org/repo.git",
    "Authorization: Bearer <your-token-here-123456>",
])
def test_safe_things_are_kept(safe):
    out, counts = mask(safe)
    assert out == safe and counts == {}


def test_boilerplate_removed_content_kept():
    text = "Prev Up Next\nSubmit correction. If you see anything in the documentation that is not correct, tell us.\nReal content stays.\nHome\n"
    assert strip_boilerplate(text) == "Real content stays.\n"


def test_exact_duplicates_dropped_and_counted():
    base = {"source": "kafka", "product": "kafka"}
    pages = [{**base, "source_path": "a", "text": "Hello   World\n\nfoo"},
             {**base, "source_path": "b", "text": "hello world foo"},
             {**base, "source_path": "c", "text": "different"}]
    kept, stats = clean_pages(pages)
    assert [p["source_path"] for p in kept] == ["a", "c"]
    assert stats["duplicates_dropped"] == {"kafka": 1}


def test_masking_counts_flow_through_clean_pages():
    pages = [{"source": "stackoverflow", "product": "github", "source_path": "q1",
              "text": f"token {FAKE['GITHUB_TOKEN']} and bob@acme-corp.io"}]
    kept, stats = clean_pages(pages)
    assert stats["masked"] == {"GITHUB_TOKEN": 1, "EMAIL": 1}
    assert FAKE["GITHUB_TOKEN"] not in kept[0]["text"]


def test_html_keeps_headings_code_and_tables():
    html = ("<h2>Fix it</h2><p>Run <code>kubectl get pods</code>.</p><pre>line1\nline2</pre>"
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
            "<div class='navfooter'>x</div>")
    out = html_to_md(html)
    assert "## Fix it" in out and "`kubectl get pods`" in out
    assert "```\nline1\nline2\n```" in out
    assert "| A | B |" in out and "| 1 | 2 |" in out


def test_markdown_dialects_cleaned_code_and_tables_kept():
    md = ("<!-- license -->\n{{< note >}}Careful.{{< /note >}}\n"
          "Use {{< glossary_tooltip text=\"Pod\" term_id=\"pod\" >}} and "
          "{% data variables.product.prodname_actions %} see [docs](/x/y).\n\n"
          "```yaml\nkey: ${{ secrets.X }}\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    out = md_to_text(md)
    assert "license" not in out and "{%" not in out and "{{<" not in out
    assert "**Note:** Careful." in out and "Use Pod and GitHub Actions see docs." in out
    assert "key: ${{ secrets.X }}" in out and "| a | b |" in out


def test_chunks_respect_size_and_overlap():
    tok = load_tokenizer("BAAI/bge-small-en-v1.5")
    text = " ".join(f"word{i}" for i in range(400))
    chunks = chunk_text(text, tok, size=50, overlap=10)
    assert len(chunks) > 5
    assert all(c["n_tokens"] <= 50 for c in chunks)
    assert chunks[-1]["text"].endswith("word399")
    for a, b in zip(chunks, chunks[1:]):  # neighbours share text
        assert b["text"].split()[0] in a["text"]
    assert chunk_text("", tok, 50, 10) == []


def test_access_levels_and_doc_types():
    rules = load_access_rules()
    page = lambda product, path, title="t", source="docs": {"product": product, "source_path": path, "title": title, "source": source}  # noqa: E731
    assert access_level(page("kafka", "kafka/security/authorization-and-acls.md"), rules) == "restricted"
    assert access_level(page("github", "github/how-tos/secure-your-work/x.md"), rules) == "restricted"
    assert access_level(page("kafka", "kafka/operations/monitoring.md"), rules) == "internal"
    assert access_level(page("postgres", "postgres/auth-pg-hba-conf.html"), rules) == "restricted"
    assert access_level(page("kubernetes", "kubernetes/tasks/debug/debug-application/debug-pods.md"), rules) == "public"
    assert doc_type({**page("kubernetes", "kubernetes/tasks/debug/debug-application/debug-pods.md"), "native_type": "task"}) == "troubleshooting"
    assert doc_type(page("github", "stackoverflow/1", source="stackoverflow")) == "qa"
    assert doc_type({**page("kubernetes", "kubernetes/concepts/x.md"), "native_type": "concept"}) == "concept"


# ---------- heading-aware chunking ----------
from src.ingest.chunk import chunk_markdown, split_blocks  # noqa: E402

DOC = """# Title

Intro words here.

## Install

Run this:

```bash
kubectl get pods

kubectl describe pod x
```

## Flags

| flag | meaning |
|------|---------|
| -a | all |

| -b | none |

## Last

Done.
"""


def test_blocks_keep_code_and_table_whole():
    kinds = [k for k, _ in split_blocks(DOC)]
    assert kinds.count("code") == 1
    code = next(b for k, b in split_blocks(DOC) if k == "code")
    assert "kubectl get pods\n\nkubectl describe pod x" in code  # blank line inside fence kept
    table = next(b for k, b in split_blocks(DOC) if k == "table")
    assert table.count("\n") == 2  # header, separator, one row


def test_chunks_split_at_headings_and_keep_blocks_intact():
    tok = load_tokenizer("BAAI/bge-small-en-v1.5")
    chunks = chunk_markdown(DOC, tok, size=30, min_tokens=1)
    texts = [c["text"] for c in chunks]
    assert any(t.startswith("## Install") for t in texts) and any(t.startswith("## Last") for t in texts)
    for t in texts:
        assert t.count("```") % 2 == 0  # no chunk cuts a code block in half
    assert any("kubectl get pods\n\nkubectl describe pod x" in t for t in texts)


def test_tiny_sections_merge_and_oversized_code_splits_with_fence():
    tok = load_tokenizer("BAAI/bge-small-en-v1.5")
    assert len(chunk_markdown(DOC, tok, size=500, min_tokens=100)) == 1  # all small -> one chunk
    big = "## Big\n\n```\n" + "\n".join(f"line {i} of a long listing" for i in range(80)) + "\n```\n"
    chunks = chunk_markdown(big, tok, size=100, min_tokens=1)
    assert len(chunks) > 1 and all(c["text"].count("```") % 2 == 0 for c in chunks)
    assert all(c["text"].startswith("## Big") for c in chunks)
    assert all(c["n_tokens"] <= 100 for c in chunks)


def test_oversized_table_repeats_header():
    tok = load_tokenizer("BAAI/bge-small-en-v1.5")
    tbl = "## T\n\n| a | b |\n|---|---|\n" + "\n".join(f"| row{i} | value number {i} |" for i in range(60)) + "\n"
    chunks = chunk_markdown(tbl, tok, size=80, min_tokens=1)
    assert len(chunks) > 1 and all("| a | b |" in c["text"] for c in chunks)
