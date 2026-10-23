"""Create the secrets in .env, the 3 demo users (config.yaml `auth.demo_users`) and their passwords. Run once:  python -m scripts.setup_users

Order on a fresh machine:
  1. python -m scripts.setup_users      writes JWT_SECRET, PASSWORD_PEPPER and MONGO_PASSWORD to .env, then says MongoDB is not running yet
  2. docker compose up -d mongo         the database reads MONGO_PASSWORD the first time it starts
  3. python -m scripts.setup_users      creates the users in MongoDB and PRINTS THE PASSWORDS ONCE

Only salted, peppered scrypt hashes are stored (users collection). Running again keeps existing users and passwords; `--reset` makes new
passwords (and prints them). The users and their licenses are SIMULATED.
"""
import argparse
import os
import secrets
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from src.access import open_store
from src.auth import hash_password
from src.llm import load_config

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ("JWT_SECRET", "PASSWORD_PEPPER", "MONGO_PASSWORD")


def ensure_env():
    env = ROOT / ".env"
    have = dotenv_values(env) if env.exists() else {}
    added = [k for k in SECRETS if not have.get(k)]
    if added:
        text = env.read_text(encoding="utf8") if env.exists() else ""
        lines = [l for l in text.splitlines() if l.split("=", 1)[0] not in added]  # replace an empty `KEY=` line from .env.example
        lines += [f"{k}={secrets.token_urlsafe(48)}" for k in added]
        env.write_text("\n".join(lines) + "\n", encoding="utf8")
        for k in added:
            os.environ[k] = dotenv_values(env)[k]
        print("Added to .env:", ", ".join(added))
    return added


def connect(cfg, wait=20):
    store = open_store(cfg)
    for i in range(wait):
        try:
            store.db.command("ping")
            return store
        except PyMongoError:
            time.sleep(1)
    sys.exit("MongoDB is not reachable on %s:%s. Start it with `docker compose up -d mongo`, then run this again." % (cfg["mongo"]["host"], cfg["mongo"]["port"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="generate new passwords for all demo users")
    ap.add_argument("--user", help="with --reset: only this demo user (for example --reset --user admin)")
    a = ap.parse_args()
    cfg = load_config()
    ensure_env()
    store = connect(cfg)
    store.licenses.create_index([("user_id", ASCENDING), ("product", ASCENDING)], unique=True)
    users = cfg["auth"]["demo_users"]
    admin = next(u["user"] for u in users if u["role"] == "admin")
    store.bootstrap_admin(admin)
    printed = []
    for u in users:
        fresh = store.password_hash(u["user"]) is None
        if u["role"] != "admin":
            store.add_user(admin, u["user"], u["role"])
            for product in u["licenses"]:
                store.grant(admin, u["user"], product)
        if fresh or (a.reset and a.user in (None, u["user"])):
            password = secrets.token_urlsafe(12)
            store.set_password_hash(u["user"], hash_password(password))
            printed.append((u["user"], u["role"], ", ".join(u["licenses"]) or "-", password))
    if printed:
        print("\nDemo users (the passwords are shown only now; copy them):")
        print(f"{'user':8} {'role':8} {'licenses':22} password")
        for row in printed:
            print(f"{row[0]:8} {row[1]:8} {row[2]:22} {row[3]}")
    else:
        print("All demo users already have passwords (use --reset to generate new ones).")


if __name__ == "__main__":
    main()
