"""Create the 3 demo users (config.yaml `auth.demo_users`) and the JWT secret. Run once:  python -m scripts.setup_users

Passwords are generated here and PRINTED ONCE; only their salted hashes are stored (data/access.db, git-ignored). JWT_SECRET is
appended to .env if it is not there (.env is git-ignored). Running it again keeps existing users and passwords; `--reset` makes
new passwords (and prints them). The users and their licenses are SIMULATED.
"""
import argparse
import secrets
from pathlib import Path

from dotenv import dotenv_values

from src.access import AccessStore
from src.auth import ensure_table, set_password
from src.llm import load_config

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="generate new passwords for all demo users")
    a = ap.parse_args()
    cfg = load_config()
    env = ROOT / ".env"
    if "JWT_SECRET" not in dotenv_values(env):
        with env.open("a", encoding="utf8") as f:
            f.write(("" if not env.exists() or env.read_text(encoding="utf8").endswith("\n") else "\n") + f"JWT_SECRET={secrets.token_urlsafe(48)}\n")
        print("JWT_SECRET added to .env")
    store = AccessStore(cfg=cfg)
    ensure_table(store)
    users = cfg["auth"]["demo_users"]
    admin = next(u["user"] for u in users if u["role"] == "admin")
    store.bootstrap_admin(admin)
    printed = []
    for u in users:
        if u["role"] != "admin":
            store.add_user(admin, u["user"], u["role"])
            for product in u["licenses"]:
                store.grant(admin, u["user"], product)
        has_password = store.db.execute("SELECT 1 FROM credentials WHERE user_id=?", (u["user"],)).fetchone()
        if a.reset or not has_password:
            password = secrets.token_urlsafe(12)
            set_password(store, u["user"], password)
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
