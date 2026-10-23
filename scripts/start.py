"""Start the whole system with one command, checking each part first:  launch.cmd   (or  python -m scripts.start)

Order: .env secrets -> Docker Desktop -> Qdrant + MongoDB containers -> demo users (first run only) -> local models on disk ->
the API (uvicorn :8000) -> the web app (Next.js :3000) -> LM Studio server + the failsafe model -> a smoke test -> your browser.
(LM Studio goes last so its model load does not slow the API and web start.)

Anything already running is reused, never started twice. Required parts (Docker, MongoDB, Qdrant + index, models, API, web) stop the start if
they fail; optional parts (LM Studio failsafe, Groq key) only warn, because the app still works without them.
Ctrl+C stops the API and web app this script started. Docker and LM Studio are left running (--stop-docker also stops the containers).

    --status        only report what is up, start nothing
    --prod          build and run the web app in production mode instead of `next dev`
    --no-open       do not open the browser
    --skip-lm       do not touch LM Studio (Groq is the default writer; the local model is only the failsafe)
    --stop-docker   on exit also run `docker compose stop`
Logs of everything started here: logs/start/*.log
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs" / "start"
PY = sys.executable
API, WEB = "http://127.0.0.1:8000", "http://127.0.0.1:3000"
DOCKER_DESKTOP = [r"C:\Program Files\Docker\Docker\Docker Desktop.exe", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Docker/Docker/Docker Desktop.exe")]
results = []   # (name, state, detail); state: ok | warn | FAIL | skip
children = []  # (name, Popen) started by this script


# ---------- small helpers ----------

def say(text=""):
    print(text, flush=True)


def record(name, state, detail=""):
    results.append((name, state, detail))
    say(f"  [{state:>4}] {name}" + (f": {detail}" if detail else ""))
    return state


def http_ok(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def run(cmd, log, timeout=None, cwd=ROOT, **kw):
    """Run a command with its output in a log file (spinners and progress bars would flood the console). Returns the exit code."""
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / log, "w", encoding="utf8", errors="replace") as f:
        try:
            return subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, **kw).returncode
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            f.write(f"\n{type(e).__name__}: {e}\n")
            return 1


def tail(log, n=8):
    try:
        return "\n".join("        " + l for l in (LOGS / log).read_text(encoding="utf8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def wait_for(check, seconds, label, every=3):
    """Poll `check` until it is true; prints the elapsed time so a slow start is visibly slow, not stuck."""
    start = time.time()
    while time.time() - start < seconds:
        if check():
            return True
        say(f"        ... waiting for {label} ({int(time.time() - start)}s of up to {seconds}s)")
        time.sleep(every)
    return check()


def spawn(name, cmd, log, cwd=ROOT):
    LOGS.mkdir(parents=True, exist_ok=True)
    f = open(LOGS / log, "w", encoding="utf8", errors="replace")
    p = subprocess.Popen(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    children.append((name, p))
    return p


def kill_tree(p):
    if p.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_cfg():
    sys.path.insert(0, str(ROOT))
    from src.llm import load_config
    return load_config()


# ---------- the steps ----------

def step_env(status_only):
    from dotenv import dotenv_values
    env = ROOT / ".env"
    have = dotenv_values(env) if env.exists() else {}
    missing = [k for k in ("JWT_SECRET", "PASSWORD_PEPPER", "MONGO_PASSWORD") if not have.get(k)]
    if missing and not status_only:
        from scripts.setup_users import ensure_env
        ensure_env()
        record(".env secrets", "ok", "created " + ", ".join(missing))
    elif missing:
        record(".env secrets", "FAIL", "missing " + ", ".join(missing) + " (a normal start creates them)")
    else:
        record(".env secrets", "ok", "JWT_SECRET, PASSWORD_PEPPER, MONGO_PASSWORD present")
    os.environ.update({k: v for k, v in dotenv_values(env).items() if v})
    record("Groq key", "ok" if have.get("GROQ_API_KEY") else "warn",
           "GROQ_API_KEY set" if have.get("GROQ_API_KEY") else "GROQ_API_KEY is empty in .env: the default writer cannot run, only the weak local failsafe")


def docker_up():
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def step_docker(status_only):
    if not shutil.which("docker"):
        return record("Docker", "FAIL", "docker is not installed or not on PATH")
    if docker_up():
        return record("Docker", "ok", "engine is running")
    if status_only:
        return record("Docker", "FAIL", "engine is not running")
    exe = next((p for p in DOCKER_DESKTOP if Path(p).exists()), None)
    if not exe:
        return record("Docker", "FAIL", "engine is not running and Docker Desktop was not found; start it yourself")
    say("  Docker engine is down: starting Docker Desktop")
    subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait_for(docker_up, 240, "the Docker engine", every=5):
        return record("Docker", "ok", "Docker Desktop started")
    return record("Docker", "FAIL", "the engine did not come up in 240 s")


def step_containers(cfg, status_only):
    from pymongo.errors import PyMongoError
    from src.access import open_store
    if not status_only:
        say("  docker compose up -d (first start pulls images; log: logs/start/compose.log)")
        code = run(["docker", "compose", "up", "-d"], "compose.log", timeout=900)
        if code:
            record("Containers", "FAIL", "docker compose up failed:\n" + tail("compose.log"))
            return None
    store = open_store(cfg)

    def mongo_up():
        try:
            store.db.command("ping")
            return True
        except PyMongoError:
            return False
    mongo = mongo_up() if status_only else wait_for(mongo_up, 90, "MongoDB")
    record("MongoDB", "ok" if mongo else "FAIL", f"{cfg['mongo']['host']}:{cfg['mongo']['port']}" if mongo else "not reachable (wrong MONGO_PASSWORD after a volume was created with another one?)")
    q = cfg["qdrant"]["url"]
    # Qdrant loads every collection before it answers, which took about 1.5 minutes on this machine.
    qdrant = http_ok(f"{q}/readyz") if status_only else wait_for(lambda: http_ok(f"{q}/readyz"), 240, "Qdrant (it loads all collections first)", every=5)
    record("Qdrant", "ok" if qdrant else "FAIL", q if qdrant else "not ready")
    if qdrant:
        coll = cfg["qdrant"]["collection"]
        have = http_ok(f"{q}/collections/{coll}")
        record(f"Index '{coll}'", "ok" if have else "FAIL", "present" if have else "missing: run  python -m src.index")
    return store if mongo else None


def step_users(store, status_only):
    if store is None:
        return
    n = store.users.count_documents({})
    admins = store.users.count_documents({"role": "admin"})
    if n and admins:
        return record("Users", "ok", f"{n} users in MongoDB (passwords are not recoverable; reset: python -m scripts.setup_users --reset)")
    if status_only:
        return record("Users", "FAIL", "no users yet (a normal start creates the demo users)")
    say("  No users yet: creating the demo users. THE PASSWORDS ARE SHOWN ONLY NOW, copy them:")
    code = subprocess.run([PY, "-m", "scripts.setup_users"], cwd=ROOT).returncode
    record("Users", "ok" if code == 0 else "FAIL", "demo users created" if code == 0 else "setup_users failed")


def step_models(cfg):
    from huggingface_hub import try_to_load_from_cache
    # scripts.download_models skips the ONNX copies on purpose, so "is the snapshot complete" is the wrong question: ask whether the
    # model's config and weights are in the cache, which is all `local_files_only=True` loading needs.
    missing = [cfg["models"][r] for r in ("embedding", "reranker", "nli")
               if not isinstance(try_to_load_from_cache(cfg["models"][r], "config.json"), str)]
    if missing:
        record("Local models", "FAIL", "not downloaded: " + ", ".join(missing) + "  -> python -m scripts.download_models")
    else:
        record("Local models", "ok", "embedding, reranker and NLI are on disk (they load inside the API, on CPU)")


def step_lmstudio(cfg, skip, status_only):
    local = cfg["llm"]["local"]
    base, model = local["base_url"].rstrip("/"), local["model"]
    if skip:
        return record("LM Studio", "skip", "skipped (--skip-lm); the failsafe writer will not be available")
    lms = shutil.which("lms") or str(Path.home() / ".lmstudio/bin/lms.exe")
    if not Path(lms).exists() and not shutil.which("lms"):
        return record("LM Studio", "warn", "the `lms` command was not found; Groq-only (install LM Studio's CLI: lms bootstrap)")

    def loaded():
        out = subprocess.run([lms, "ps"], capture_output=True, text=True, timeout=30).stdout
        return model in out

    if not http_ok(f"{base}/models"):
        if status_only:
            return record("LM Studio", "warn", "server is not running")
        say("  starting the LM Studio server")
        run([lms, "server", "start"], "lms-server.log", timeout=90)
        wait_for(lambda: http_ok(f"{base}/models"), 45, "the LM Studio server", every=3)
    if not http_ok(f"{base}/models"):
        return record("LM Studio", "warn", "server did not start; Groq-only. " + tail("lms-server.log", 3).strip())
    try:
        if loaded():
            return record("LM Studio", "ok", f"server up, {model} loaded")
    except Exception:
        pass
    if status_only:
        return record("LM Studio", "warn", f"server up but {model} is not loaded")
    say(f"  loading {model} (about 30 s; log: logs/start/lms-load.log)")
    code = run([lms, "load", model, "-y", "--context-length", "4096"], "lms-load.log", timeout=300)
    ok = code == 0 and loaded()
    record("LM Studio", "ok" if ok else "warn", f"{model} loaded" if ok else "could not load the model; Groq-only. " + tail("lms-load.log", 3).strip())


def step_api(status_only):
    if http_ok(f"{API}/health"):
        return record("API", "ok", f"{API} (already running)")
    if status_only:
        return record("API", "FAIL", "not running")
    say("  starting the API (loading the models takes a little while)")
    p = spawn("API", [PY, "-m", "uvicorn", "src.api:app", "--host", "127.0.0.1", "--port", "8000"], "api.log")
    up = wait_for(lambda: http_ok(f"{API}/health") or p.poll() is not None, 300, "the API")  # over 120 s was seen with Qdrant still loading
    if http_ok(f"{API}/health"):
        return record("API", "ok", f"{API}  (log: logs/start/api.log)")
    record("API", "FAIL", "did not start:\n" + tail("api.log"))


def step_web(status_only, prod):
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if http_ok(f"{WEB}/login"):
        return record("Web app", "ok", f"{WEB} (already running)")
    if status_only:
        return record("Web app", "FAIL", "not running")
    if not npm:
        return record("Web app", "FAIL", "Node.js / npm not found on PATH")
    web = ROOT / "web"
    if not (web / "node_modules").exists():
        say("  first run: npm install (takes about a minute)")
        if subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=web).returncode:
            return record("Web app", "FAIL", "npm install failed")
    if prod:
        say("  building the web app for production")
        if run([npm, "run", "build"], "web-build.log", cwd=web, timeout=600):
            return record("Web app", "FAIL", "build failed:\n" + tail("web-build.log"))
    p = spawn("Web", [npm, "run", "start" if prod else "dev", "--", "--port", "3000", "--hostname", "127.0.0.1"], "web.log", cwd=web)
    wait_for(lambda: http_ok(f"{WEB}/login", 30) or p.poll() is not None, 240, "the web app")  # 100 s was seen when the machine was busy
    if http_ok(f"{WEB}/login", 30):
        return record("Web app", "ok", f"{WEB} ({'production' if prod else 'dev'} mode; log: logs/start/web.log)")
    record("Web app", "FAIL", "did not start:\n" + tail("web.log"))


def step_smoke():
    ok = all(http_ok(f"{WEB}/api/backend/{p}", 20) for p in ("metrics", "documents"))
    record("End-to-end check", "ok" if ok else "FAIL", "browser -> web app -> API -> data works" if ok else "the web app cannot reach the API")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("--status", "--prod", "--no-open", "--skip-lm", "--stop-docker"):
        ap.add_argument(flag, action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    say(f"SupportRAG {'status' if a.status else 'start'}  ({time.strftime('%H:%M:%S')})\n")
    cfg = load_cfg()

    say("Checking and starting:")
    step_env(a.status)
    store = None
    if step_docker(a.status) == "ok":
        store = step_containers(cfg, a.status)
        step_users(store, a.status)
    step_models(cfg)
    # the API and the web app need MongoDB and Qdrant; do not start them on top of a broken base
    base_ok = store is not None and not any(s == "FAIL" for n, s, _ in results if n in ("Qdrant",) or n.startswith("Index") or n == "Local models")
    if base_ok or a.status:
        step_api(a.status)
        step_web(a.status, a.prod)
        if not a.status and all(s != "FAIL" for n, s, _ in results if n in ("API", "Web app")):
            step_smoke()
    else:
        record("API / Web app", "skip", "not started: fix the FAIL lines above first")
    # LM Studio last: it only serves the failsafe writer, and loading its model would compete for CPU, RAM and disk with the slow steps above
    step_lmstudio(cfg, a.skip_lm, a.status)

    failed = [r for r in results if r[1] == "FAIL"]
    say("\n" + "=" * 64)
    say("READY" if not failed else "NOT READY: " + ", ".join(r[0] for r in failed))
    if not failed:
        say(f"  Web app   {WEB}\n  API docs  {API}/docs\n  Logs      logs/start/")
        say("  Sign in as admin, alice or bob (passwords: shown once at creation; reset with  python -m scripts.setup_users --reset)")
    say("=" * 64)
    if a.status or failed:
        for _, p in children:
            kill_tree(p)
        sys.exit(1 if failed else 0)
    if not a.no_open:
        webbrowser.open(WEB)
    if not children:
        say("Everything was already running; nothing for this script to supervise.")
        return
    say("Press Ctrl+C to stop what this script started (" + ", ".join(n for n, _ in children) + ").")
    try:
        while all(p.poll() is None for _, p in children):
            time.sleep(2)
        dead = [n for n, p in children if p.poll() is not None]
        say(f"\n{', '.join(dead)} stopped on its own; see logs/start/. Shutting down the rest.")
    except KeyboardInterrupt:
        say("\nStopping ...")
    finally:
        for _, p in children:
            kill_tree(p)
        if a.stop_docker:
            subprocess.run(["docker", "compose", "stop"], cwd=ROOT)
        say("Stopped. Docker and LM Studio are still running." if not a.stop_docker else "Stopped, including the containers.")


if __name__ == "__main__":
    main()
