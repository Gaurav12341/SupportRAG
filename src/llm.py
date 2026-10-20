"""One small LLM client: LM Studio (local) first, Groq as failsafe.

Fallback happens only if the local server is unreachable, times out, or returns unusable output. Every fallback is logged.

Evals add three things on top (all optional per call):
  cache="name"     finished replies are kept in data/cache/llm_<name>.jsonl, keyed by provider + model + messages, so a rerun
                   (or a run resumed after a quota stop) pays nothing for what is already done.
  model="..."      the Groq model for this call, so each stage can use its own free-tier bucket.
  fallback=False   no switch to the other provider; a failure is raised. Used by the judge and the verifier, whose scores
                   would be meaningless if another model answered.
  stop_on_quota    a used-up Groq daily limit is raised, not answered by the other provider (other failures still fall back).
Groq calls are paced per model (requests/min, tokens/min, tokens/day, from `llm.groq.limits`). A per-minute limit makes the
client wait; a used-up daily limit raises QuotaExhausted so an eval can stop cleanly and be re-run later.
"""
import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

load_dotenv()

log = logging.getLogger("supportrag.llm")
ROOT = Path(__file__).resolve().parent.parent


class UnusableOutput(RuntimeError):
    """The provider answered, but with nothing usable."""


class QuotaExhausted(RuntimeError):
    """A Groq daily limit is used up (or the wait would be far too long). Retrying now is pointless; re-run later."""


@dataclass
class Reply:
    text: str
    provider: str                                   # local | groq
    model: str
    usage: dict = field(default_factory=dict)       # prompt_tokens, completion_tokens, total_tokens (0 if unknown)
    cached: bool = False                            # True = read from the disk cache, nothing was spent
    seconds: float = 0.0


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def estimate_tokens(messages: list[dict]) -> int:
    """A deliberately high guess (3 characters per token) used only to decide how long to wait before a Groq call."""
    return int(sum(len(m["content"]) for m in messages) / 3) + 50


# ---------- Groq pacing ----------

class Pacer:
    """Keeps one Groq model inside its free-tier buckets. `limits`: requests_per_min, tokens_per_min, tokens_per_day.
    The minute buckets are tracked from the usage of the calls made here and from the server's x-ratelimit-remaining-tokens
    header; the day bucket from a rolling 24-hour ledger (`usage_log`). The server is the final judge: a 429 that names a
    daily limit stops the run, any other 429 is waited out."""

    MAX_WAIT_S = 90  # a per-minute limit never needs longer; more means a daily limit

    def __init__(self, model, limits, ledger=None, clock=time.time, sleep=time.sleep):
        self.model, self.limits, self.ledger, self.clock, self.sleep = model, limits, ledger, clock, sleep
        self.sent = deque()          # request times, last minute
        self.spent = deque()         # (time, tokens), last minute
        self.header = None           # (remaining tokens, time it was read)
        self.day = deque()           # (time, tokens), last 24 hours
        for row in (ledger.rows(model) if ledger else []):
            self.day.append((row["ts"], row["total_tokens"]))

    def _trim(self, now):
        while self.sent and now - self.sent[0] > 60:
            self.sent.popleft()
        while self.spent and now - self.spent[0][0] > 60:
            self.spent.popleft()
        while self.day and now - self.day[0][0] > 86400:
            self.day.popleft()

    def tokens_today(self):
        self._trim(self.clock())
        return sum(t for _, t in self.day)

    def wait_needed(self, need_tokens):
        """Seconds to wait before a call that may use `need_tokens` is allowed; raises QuotaExhausted for the day limit."""
        now, lim = self.clock(), self.limits
        self._trim(now)
        used_today = sum(t for _, t in self.day)
        if used_today + need_tokens > lim["tokens_per_day"]:
            raise QuotaExhausted(f"{self.model}: {used_today} of {lim['tokens_per_day']} tokens used in the last 24 hours")
        if len(self.day) >= lim["requests_per_day"]:
            raise QuotaExhausted(f"{self.model}: {len(self.day)} requests in the last 24 hours")
        wait = 0.0
        if len(self.sent) >= lim["requests_per_min"] - 1:  # keep one request of headroom
            wait = max(wait, 60 - (now - self.sent[0]) + 0.5)
        need = min(need_tokens, lim["tokens_per_min"] - 100)
        free = lim["tokens_per_min"] - sum(t for _, t in self.spent)
        if self.header is not None:  # the server's own count, plus what has refilled since it was read
            remaining, at = self.header
            free = min(free, remaining + (now - at) * lim["tokens_per_min"] / 60)
        if free < need:
            wait = max(wait, (need - free) * 60 / lim["tokens_per_min"] + 0.5)
        return wait

    def before(self, need_tokens, say=None):
        wait = self.wait_needed(need_tokens)
        if wait > 0:
            if say:
                say(f"[pace] {self.model}: waiting {wait:.0f}s for the minute bucket")
            self.sleep(wait)

    def after(self, usage, headers, purpose=""):
        now, total = self.clock(), int(usage.get("total_tokens", 0))
        self.sent.append(now)
        self.spent.append((now, total))
        self.day.append((now, total))
        if (rem := (headers or {}).get("x-ratelimit-remaining-tokens")) is not None:
            self.header = (float(rem), now)
        if self.ledger:
            self.ledger.add(self.model, purpose, usage, now)

    def on_429(self, err, say=None):
        """Wait out a per-minute limit; raise QuotaExhausted for a daily one."""
        msg = str(getattr(err, "message", err))
        hdrs = getattr(getattr(err, "response", None), "headers", {}) or {}
        m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?", msg)
        hinted = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)) if m else 0
        retry = float(hdrs.get("retry-after") or hinted or 10)
        if re.search(r"per day|\(TPD\)|\(RPD\)", msg) or retry > self.MAX_WAIT_S:
            raise QuotaExhausted(f"{self.model}: daily limit reached (server says retry in {retry / 60:.0f} min). {msg[:200]}")
        if say:
            say(f"[pace] {self.model}: 429, waiting {retry + 1:.0f}s")
        self.sleep(retry + 1)


class UsageLedger:
    """Append-only record of every Groq call's token usage (data/cache/groq_usage.jsonl); the daily limit is read from it."""

    def __init__(self, path):
        self.path = Path(path)
        self._rows = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf8").splitlines():
                try:
                    self._rows.append(json.loads(line))
                except ValueError:
                    pass  # a line cut off by a crash

    def rows(self, model):
        return [r for r in self._rows if r["model"] == model]

    def add(self, model, purpose, usage, ts):
        row = {"ts": ts, "model": model, "purpose": purpose, "prompt_tokens": usage.get("prompt_tokens", 0),
               "completion_tokens": usage.get("completion_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
        self._rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf8") as f:
            f.write(json.dumps(row) + "\n")


# ---------- reply cache ----------

class ReplyCache:
    """One JSON line per finished call; written as soon as the call ends, so an interrupted run loses nothing."""

    def __init__(self, path):
        self.path, self.rows = Path(path), {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf8").splitlines():
                try:
                    row = json.loads(line)
                    self.rows[row["key"]] = row["reply"]
                except (ValueError, KeyError):
                    pass

    def get(self, key):
        return self.rows.get(key)

    def put(self, key, reply: Reply):
        self.rows[key] = {k: v for k, v in asdict(reply).items() if k != "cached"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf8") as f:
            f.write(json.dumps({"key": key, "reply": self.rows[key]}, ensure_ascii=False) + "\n")


_caches: dict = {}
_pacers: dict = {}


class LLMClient:
    def __init__(self, cfg: dict | None = None, say=None):
        cfg = cfg or load_config()["llm"]
        self.cfg = cfg
        self.say = say                      # called with a progress line when the client waits (e.g. print)
        self.events: list[Reply] = []       # every reply this client returned, cached or not, in order
        self.local = OpenAI(
            base_url=cfg["local"]["base_url"],
            api_key="lm-studio",  # LM Studio ignores the key
            timeout=cfg["local"]["timeout_s"],
            max_retries=0,
        )
        self.groq = None  # created on first fallback so a missing key only matters then
        self._log_fallbacks_to_file(cfg.get("fallback_log"))

    @staticmethod
    def _log_fallbacks_to_file(path: str | None) -> None:
        if not path or any(isinstance(h, logging.FileHandler) for h in log.handlers):
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)

    def _call(self, client: OpenAI, model: str, messages: list[dict], **kw) -> tuple[str, dict, dict]:
        """One request. Returns (text, usage, response headers)."""
        extra = {"response_format": kw["response_format"]} if kw.get("response_format") else {}  # e.g. a JSON schema
        if kw.get("reasoning_effort"):  # Groq's gpt-oss models think before answering; "low" keeps that short
            extra["reasoning_effort"] = kw["reasoning_effort"]
        raw = client.chat.completions.with_raw_response.create(
            model=model,
            messages=messages,
            temperature=kw.get("temperature", self.cfg["temperature"]),
            max_tokens=kw.get("max_tokens", self.cfg["max_tokens"]),
            **extra,
        )
        resp = raw.parse()
        u = getattr(resp, "usage", None)
        usage = {"prompt_tokens": getattr(u, "prompt_tokens", 0) or 0, "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                 "total_tokens": getattr(u, "total_tokens", 0) or 0}
        text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S)  # some models inline their thinking
        return text.strip(), usage, dict(raw.headers)

    def _groq_client(self) -> OpenAI:
        if self.groq is None:
            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise RuntimeError("GROQ_API_KEY is not set in .env")
            self.groq = OpenAI(base_url=self.cfg["groq"]["base_url"], api_key=key,
                               timeout=self.cfg["groq"]["timeout_s"], max_retries=0)
        return self.groq

    def _pacer(self, model: str) -> Pacer:
        g = self.cfg["groq"]
        key = (model, g.get("usage_log"))
        if key not in _pacers:
            ledger = UsageLedger(ROOT / g["usage_log"]) if g.get("usage_log") else None
            _pacers[key] = Pacer(model, g["limits"], ledger) if g.get("limits") else None
        return _pacers[key]

    def _run(self, name: str, messages: list[dict], validate, model=None, purpose="", **kw) -> Reply:
        """One provider. Raises on any failure, including empty or invalid output."""
        t0 = time.perf_counter()
        if name == "local":
            model = self.cfg["local"]["model"]
            kw.pop("reasoning_effort", None)  # a Groq-only setting
            text, usage, _ = self._call(self.local, model, messages, **kw)
        else:
            g = self.cfg["groq"]
            model = model or g["model"]
            kw = {"max_tokens": g.get("max_tokens"), "reasoning_effort": g.get("reasoning_effort"), **kw}
            kw = {k: v for k, v in kw.items() if v is not None}
            pacer = self._pacer(model)
            for attempt in range(6):
                if pacer:
                    pacer.before(estimate_tokens(messages) + kw.get("max_tokens", 0), self.say)
                try:
                    text, usage, headers = self._call(self._groq_client(), model, messages, **kw)
                    break
                except RateLimitError as e:
                    if not pacer:
                        raise
                    pacer.on_429(e, self.say)
                except (APIConnectionError, APITimeoutError, InternalServerError):
                    if attempt >= 2:
                        raise
                    time.sleep(5)
            else:
                raise RuntimeError(f"{model}: still rate limited after 6 tries")
            if pacer:
                pacer.after(usage, headers, purpose)
        if not text or (validate is not None and not validate(text)):
            raise UnusableOutput(f"{name} returned unusable output")
        return Reply(text, name, model, usage, seconds=round(time.perf_counter() - t0, 2))

    def _cache_key(self, first, model, messages, kw, salt):
        used = model or (self.cfg["groq"]["model"] if first == "groq" else self.cfg["local"]["model"])
        payload = {"first": first, "model": used, "messages": messages, "salt": salt,
                   "kw": {k: v for k, v in sorted(kw.items())}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()

    def chat_full(self, messages: list[dict], validate=None, prefer: str | None = None, cache: str | None = None,
                  fallback: bool = True, model: str | None = None, salt: str = "", stop_on_quota: bool = False, **kw) -> Reply:
        """Like chat(), but returns the whole Reply (model, token usage, cached or not). `cache` names the disk cache;
        `salt` changes the cache key so a run can be repeated for real (e.g. to measure run-to-run spread). `stop_on_quota`
        raises QuotaExhausted instead of switching provider (an eval must not mix models), while other failures still fall back."""
        first = prefer or self.cfg.get("prefer", "local")
        second = "groq" if first == "local" else "local"
        store = key = None
        if cache:
            path = ROOT / self.cfg.get("cache_dir", "data/cache") / f"llm_{cache}.jsonl"
            store = _caches.setdefault(path, ReplyCache(path))
            key = self._cache_key(first, model, messages, kw, salt)
            if (hit := store.get(key)) is not None:
                reply = Reply(**hit, cached=True)
                self.events.append(reply)
                return reply
        run = dict(model=model, purpose=cache or "", **kw)

        def finish(reply):
            if store is not None:
                store.put(key, reply)
            self.events.append(reply)
            return reply

        try:
            return finish(self._run(first, messages, validate, **run))
        except QuotaExhausted:
            if not fallback or stop_on_quota:
                raise
            reason = f"QuotaExhausted for {model or first}"
        except Exception as e:  # unreachable, timeout, server error, unusable output
            if not fallback:
                raise
            reason = str(e) if isinstance(e, UnusableOutput) else f"{type(e).__name__}: {e}"
        log.warning("FALLBACK %s -> %s (%s)", first, second, reason)
        try:
            return finish(self._run(second, messages, validate, **run))
        except UnusableOutput as e:
            raise RuntimeError(f"{first} failed ({reason}) and {e} as well") from e
        except QuotaExhausted:
            raise
        except RuntimeError as e:
            if "GROQ_API_KEY" in str(e):
                raise RuntimeError(f"{first} failed ({reason}) and GROQ_API_KEY is not set in .env") from e
            raise

    def chat(self, messages: list[dict], validate=None, prefer: str | None = None, **kw) -> tuple[str, str]:
        """Return (text, provider). `validate(text) -> bool` marks output unusable. The `prefer`red provider
        (default: llm.prefer in config.yaml, else local) goes first; the other is the failsafe. Every fallback is logged.
        Extra keywords (cache, model, fallback, salt, stop_on_quota) are described in the module docstring."""
        reply = self.chat_full(messages, validate, prefer, **kw)
        return reply.text, reply.provider

    def usage_by_model(self, since: int = 0) -> dict:
        """Token totals of the replies from index `since` of `events` on: {"provider/model": {calls, cached_calls,
        prompt_tokens, completion_tokens, total_tokens, fresh_total_tokens}}. A cached reply still counts its original
        tokens (what the result cost to produce); fresh_total_tokens leaves those out (what this run actually spent)."""
        out = {}
        for r in self.events[since:]:
            row = out.setdefault(f"{r.provider}/{r.model}", {"calls": 0, "cached_calls": 0, "prompt_tokens": 0,
                                                              "completion_tokens": 0, "total_tokens": 0, "fresh_total_tokens": 0})
            row["calls"] += 1
            row["cached_calls"] += r.cached
            row["fresh_total_tokens"] += 0 if r.cached else r.usage.get("total_tokens", 0)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                row[k] += r.usage.get(k, 0)
        return out
