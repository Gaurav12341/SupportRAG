"""Who may read what (stages 7 and 9). SIMULATED on public docs; the rules are real, the data is not.

Roles:
  public  anyone, not logged in: chunks of level `base_levels` (public), for every product.
  member  logged in, with product licenses: public chunks of every product, plus `licensed_levels`
          (internal, restricted) of the products they are licensed for. No license for a product = public chunks only.
  admin   everything, and the only role that may grant or revoke licenses.

One rule, two forms: `qdrant_filter()` (used inside the Qdrant query) and `allows()` (used for BM25, before ranking).
Both are built from the same fields, and a test checks they agree on every chunk. Missing or unknown data is denied.

Users, password hashes, licenses and an audit log of every change live in MongoDB (docker-compose service `mongo`, config.yaml `mongo`).
Nothing here proves who a caller is: login (src/auth.py) produces the `user_id` used below.
"""
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from qdrant_client import models

load_dotenv()

ROLES = ("public", "member", "admin")
PRODUCTS = ("kubernetes", "postgres", "kafka", "github")
ROOT = Path(__file__).resolve().parent.parent
USER_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")  # lower-case, 2-32 characters
_open = {}  # one client per process (MongoClient is thread-safe and pools connections)


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


def open_store(cfg):
    """The AccessStore on the MongoDB from config.yaml `mongo` (password from .env MONGO_PASSWORD). The client is shared and connects on first use (the unique license index is made by scripts.setup_users)."""
    m = cfg["mongo"]
    if "store" not in _open:
        password = os.getenv("MONGO_PASSWORD")
        if not password:
            raise RuntimeError("MONGO_PASSWORD is missing in .env; run `python -m scripts.setup_users`")
        client = MongoClient(f"mongodb://{quote_plus(m['user'])}:{quote_plus(password)}@{m['host']}:{m['port']}/?authSource=admin",
                             serverSelectionTimeoutMS=m.get("timeout_ms", 3000))
        _open["store"] = AccessStore(client[m["db"]])
    return _open["store"]


class AccessStore:
    """Users, roles, password hashes and product licenses in MongoDB. Only an admin can change licenses or add users; every change is logged.

    Collections: users {_id: user_id, role, password_hash, created_at, created_by}, licenses {user_id, product, granted_by, granted_at},
    audit {at, actor, action, user_id, product}. `db` is a pymongo Database (tests pass a mongomock one).
    """

    def __init__(self, db):
        self.db = db
        self.users, self.licenses, self.audit = db["users"], db["licenses"], db["audit"]

    # ----- reading -----
    def role_of(self, user_id):
        row = self.users.find_one({"_id": user_id}, {"role": 1})
        return row["role"] if row else None

    def licenses_of(self, user_id):
        return sorted(r["product"] for r in self.licenses.find({"user_id": user_id}))

    def principal(self, user_id=None):
        """Who is this caller? No user or an unknown user = public (never an error that leaks more access)."""
        role = self.role_of(user_id) if user_id else None
        if role == "admin":
            return Principal.admin()
        if role == "member":
            return Principal.member(*self.licenses_of(user_id))
        return Principal.public()

    def password_hash(self, user_id):
        row = self.users.find_one({"_id": user_id}, {"password_hash": 1})
        return row.get("password_hash") if row else None

    def list_users(self):
        """Every user with role and licenses, for the admin screen (never the password hash)."""
        by_user = {}
        for r in self.licenses.find():
            by_user.setdefault(r["user_id"], []).append(r["product"])
        return [{"user": u["_id"], "role": u["role"], "licenses": sorted(by_user.get(u["_id"], [])), "created_at": u.get("created_at"), "created_by": u.get("created_by")}
                for u in self.users.find({}, {"role": 1, "created_at": 1, "created_by": 1}).sort("_id", ASCENDING)]

    def audit_log(self):
        return [(r["at"], r["actor"], r["action"], r["user_id"], r["product"]) for r in self.audit.find().sort("_id", ASCENDING)]

    def recent_audit(self, n=20):
        return [{k: r[k] for k in ("at", "actor", "action", "user_id", "product")} for r in self.audit.find().sort("_id", -1).limit(n)]

    # ----- changing (admin only, except the setup helpers) -----
    def _require_admin(self, actor):
        if self.role_of(actor) != "admin":
            raise PermissionError(f"{actor!r} is not an admin")

    def _log(self, actor, action, user_id, product=None):
        self.audit.insert_one({"at": time.time(), "actor": actor, "action": action, "user_id": user_id, "product": product})

    def bootstrap_admin(self, user_id):
        """The very first admin, created from a trusted place (a setup script), never through a request."""
        self.users.update_one({"_id": user_id}, {"$set": {"role": "admin"}, "$setOnInsert": {"created_at": time.time(), "created_by": "setup"}}, upsert=True)
        self._log("setup", "bootstrap_admin", user_id)

    def add_user(self, actor, user_id, role="member", password_hash=None):
        """Create a user, or change an existing user's role (and password if one is given). The hash is made by src.auth, never the plain password."""
        self._require_admin(actor)
        if role not in ("member", "admin"):
            raise ValueError("role must be 'member' or 'admin'")
        if not USER_ID.match(user_id or ""):
            raise ValueError("user name must be 2-32 characters: lower-case letters, digits, '.', '_' or '-', starting with a letter or digit")
        update = {"$set": {"role": role}, "$setOnInsert": {"created_at": time.time(), "created_by": actor}}
        if password_hash:
            update["$set"]["password_hash"] = password_hash
        self.users.update_one({"_id": user_id}, update, upsert=True)
        if role == "admin":  # admins see everything; licenses would only confuse
            self.licenses.delete_many({"user_id": user_id})
        self._log(actor, f"add_user:{role}", user_id)

    def set_password_hash(self, user_id, password_hash):
        """Store a hash made by src.auth.hash_password. Used by the setup script and by the admin when creating a user."""
        if self.users.update_one({"_id": user_id}, {"$set": {"password_hash": password_hash}}).matched_count == 0:
            raise ValueError(f"unknown user {user_id!r}")

    def grant(self, actor, user_id, product):
        self._require_admin(actor)
        if product not in PRODUCTS:
            raise ValueError(f"unknown product {product!r}; known products: {list(PRODUCTS)}")
        if self.role_of(user_id) != "member":
            raise ValueError(f"{user_id!r} is not a member (licenses are for members; admins see everything)")
        self.licenses.update_one({"user_id": user_id, "product": product}, {"$setOnInsert": {"granted_by": actor, "granted_at": time.time()}}, upsert=True)
        self._log(actor, "grant", user_id, product)

    def revoke(self, actor, user_id, product):
        self._require_admin(actor)
        self.licenses.delete_many({"user_id": user_id, "product": product})
        self._log(actor, "revoke", user_id, product)
