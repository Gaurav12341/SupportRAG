"""Who may read what (stages 7 and 9). SIMULATED on public docs; the rules are real, the data is not.

Roles:
  public  anyone, not logged in: chunks of level `base_levels` (public), for every product.
  member  logged in, with product licenses: public chunks of every product, plus `licensed_levels`
          (internal, restricted) of the products they are licensed for. No license for a product = public chunks only.
  admin   everything, and the only role that may grant or revoke licenses.

One rule, two forms: `qdrant_filter()` (used inside the Qdrant query) and `allows()` (used for BM25, before ranking).
Both are built from the same fields, and a test checks they agree on every chunk. Missing or unknown data is denied.

Licenses live in a small SQLite file (`paths.access_db`), with an audit log of every grant/revoke.
Nothing here proves who a caller is: login is stage 7 and will produce the `user_id` used below.
"""
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import models

ROLES = ("public", "member", "admin")
PRODUCTS = ("kubernetes", "postgres", "kafka", "github")
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Principal:
    role: str = "public"
    licenses: frozenset = frozenset()  # products a member is licensed for

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"unknown role {self.role!r}; known roles: {list(ROLES)}")
        bad = set(self.licenses) - set(PRODUCTS)
        if bad:
            raise ValueError(f"unknown product(s) {sorted(bad)}; known products: {list(PRODUCTS)}")
        if self.role == "public" and self.licenses:
            raise ValueError("the public role has no licenses; log in as a member")

    @classmethod
    def public(cls):
        return cls("public")

    @classmethod
    def member(cls, *products):
        return cls("member", frozenset(products))

    @classmethod
    def admin(cls):
        return cls("admin")

    def _rules(self, cfg):
        """(levels readable for every product, levels readable only for licensed products, licensed products)."""
        a = cfg["access"]
        if self.role == "admin":
            return list(a["admin_levels"]), [], []
        if self.role == "member":
            return list(a["base_levels"]), list(a["licensed_levels"]), sorted(self.licenses)
        return list(a["base_levels"]), [], []

    def allows(self, payload, cfg):
        """May this principal read this chunk? Same rule as qdrant_filter()."""
        everywhere, licensed_only, products = self._rules(cfg)
        level = payload.get("access_level")
        if level in everywhere:
            return True
        return level in licensed_only and payload.get("product") in products

    def qdrant_filter(self, cfg, product=None):
        """Filter for the Qdrant query. `product` is the user's own narrowing choice and is ANDed on top."""
        everywhere, licensed_only, products = self._rules(cfg)
        base = models.FieldCondition(key="access_level", match=models.MatchAny(any=everywhere))
        if licensed_only and products:
            rule = models.Filter(should=[base, models.Filter(must=[
                models.FieldCondition(key="access_level", match=models.MatchAny(any=licensed_only)),
                models.FieldCondition(key="product", match=models.MatchAny(any=products))])])
        else:
            rule = base
        must = [rule]
        if product:
            must.append(models.FieldCondition(key="product", match=models.MatchValue(value=product)))
        return models.Filter(must=must)


class AccessStore:
    """Users, roles and product licenses in SQLite. Only an admin can change licenses; every change is logged."""

    def __init__(self, path=None, cfg=None):
        path = Path(path) if path else ROOT / ((cfg or {}).get("paths", {}).get("access_db", "data/access.db"))
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK (role IN ('member','admin')));
            CREATE TABLE IF NOT EXISTS licenses (user_id TEXT NOT NULL REFERENCES users(user_id), product TEXT NOT NULL,
                granted_by TEXT NOT NULL, granted_at REAL NOT NULL, PRIMARY KEY (user_id, product));
            CREATE TABLE IF NOT EXISTS audit (at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
                user_id TEXT NOT NULL, product TEXT);
        """)

    # ----- reading -----
    def role_of(self, user_id):
        row = self.db.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else None

    def licenses_of(self, user_id):
        return sorted(p for (p,) in self.db.execute("SELECT product FROM licenses WHERE user_id=?", (user_id,)))

    def principal(self, user_id=None):
        """Who is this caller? No user or an unknown user = public (never an error that leaks more access)."""
        role = self.role_of(user_id) if user_id else None
        if role == "admin":
            return Principal.admin()
        if role == "member":
            return Principal.member(*self.licenses_of(user_id))
        return Principal.public()

    def audit_log(self):
        return self.db.execute("SELECT at, actor, action, user_id, product FROM audit ORDER BY rowid").fetchall()

    # ----- changing (admin only) -----
    def _require_admin(self, actor):
        if self.role_of(actor) != "admin":
            raise PermissionError(f"{actor!r} is not an admin")

    def _log(self, actor, action, user_id, product=None):
        self.db.execute("INSERT INTO audit VALUES (?,?,?,?,?)", (time.time(), actor, action, user_id, product))

    def bootstrap_admin(self, user_id):
        """The very first admin, created from a trusted place (a setup script), never through a request."""
        self.db.execute("INSERT OR REPLACE INTO users VALUES (?, 'admin')", (user_id,))
        self._log("setup", "bootstrap_admin", user_id)
        self.db.commit()

    def add_user(self, actor, user_id, role="member"):
        self._require_admin(actor)
        if role not in ("member", "admin"):
            raise ValueError("role must be 'member' or 'admin'")
        self.db.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (user_id, role))
        self._log(actor, f"add_user:{role}", user_id)
        self.db.commit()

    def grant(self, actor, user_id, product):
        self._require_admin(actor)
        if product not in PRODUCTS:
            raise ValueError(f"unknown product {product!r}; known products: {list(PRODUCTS)}")
        if self.role_of(user_id) != "member":
            raise ValueError(f"{user_id!r} is not a member (licenses are for members; admins see everything)")
        self.db.execute("INSERT OR IGNORE INTO licenses VALUES (?,?,?,?)", (user_id, product, actor, time.time()))
        self._log(actor, "grant", user_id, product)
        self.db.commit()

    def revoke(self, actor, user_id, product):
        self._require_admin(actor)
        self.db.execute("DELETE FROM licenses WHERE user_id=? AND product=?", (user_id, product))
        self._log(actor, "revoke", user_id, product)
        self.db.commit()
