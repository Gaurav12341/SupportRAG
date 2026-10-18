"""Stage 4: metadata for every chunk: product, version, source path, doc type, simulated access level."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
LEVELS = ("public", "internal", "restricted")


def load_access_rules(path=None):
    cfg = yaml.safe_load((Path(path) if path else ROOT / "configs" / "access_rules.yaml").read_text(encoding="utf8"))
    for r in cfg["rules"]:
        assert r["level"] in LEVELS, r
        r["_rx"] = re.compile(r["path"])
    assert cfg["default"] in LEVELS
    return cfg


def access_level(page, rules):
    path = page["source_path"].lower()
    for r in rules["rules"]:
        if r.get("product", page["product"]) == page["product"] and r["_rx"].search(path):
            return r["level"]
    return rules["default"]


def doc_type(page):
    """troubleshooting | reference | tutorial | concept | howto | qa. Simple path/title rules."""
    if page["source"] == "stackoverflow":
        return "qa"
    hint = (page["source_path"] + " " + page["title"]).lower()
    if re.search(r"troubleshoot|/debug|debug-|errcodes|common-errors|error-codes", hint):
        return "troubleshooting"
    native = page.get("native_type", "").lower()
    mapped = {"concept": "concept", "concepts": "concept", "task": "howto", "how-tos": "howto",
              "tutorial": "tutorial", "tutorials": "tutorial", "reference": "reference", "snippet": "reference"}
    if native in mapped:
        return mapped[native]
    if re.search(r"/configuration/|runtime-config|config", hint):
        return "reference"
    if re.search(r"getting-started|quickstart|tutorial", hint):
        return "tutorial"
    return "concept" if page["source"] == "postgres" else "howto"


def add_metadata(page, rules):
    return {"product": page["product"], "version": page["version"], "source": page["source"],
            "source_path": page["source_path"], "url": page["url"], "title": page["title"],
            "doc_type": doc_type(page), "access_level": access_level(page, rules), "license": page["license"]}
