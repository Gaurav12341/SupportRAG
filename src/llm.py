"""One small LLM client: LM Studio (local) first, Groq as failsafe.

Fallback happens only if the local server is unreachable, times out, or
returns unusable output. Every fallback is logged.
"""
import logging
import os
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

log = logging.getLogger("supportrag.llm")


class UnusableOutput(RuntimeError):
    """The provider answered, but with nothing usable."""


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class LLMClient:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or load_config()["llm"]
        self.cfg = cfg
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

    def _call(self, client: OpenAI, model: str, messages: list[dict], **kw) -> str:
        extra = {"response_format": kw["response_format"]} if kw.get("response_format") else {}  # e.g. a JSON schema
        if kw.get("reasoning_effort"):  # Groq's gpt-oss models think before answering; "low" keeps that short
            extra["reasoning_effort"] = kw["reasoning_effort"]
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kw.get("temperature", self.cfg["temperature"]),
            max_tokens=kw.get("max_tokens", self.cfg["max_tokens"]),
            **extra,
        )
        return (resp.choices[0].message.content or "").strip()

    def _groq_client(self) -> OpenAI:
        if self.groq is None:
            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise RuntimeError("GROQ_API_KEY is not set in .env")
            self.groq = OpenAI(base_url=self.cfg["groq"]["base_url"], api_key=key,
                               timeout=self.cfg["groq"]["timeout_s"], max_retries=0)
        return self.groq

    def _run(self, name: str, messages: list[dict], validate, **kw) -> str:
        """One provider. Raises on any failure, including empty or invalid output."""
        if name == "local":
            text = self._call(self.local, self.cfg["local"]["model"], messages, **kw)
        else:
            g = self.cfg["groq"]
            kw = {"max_tokens": g.get("max_tokens"), "reasoning_effort": g.get("reasoning_effort"), **kw}
            kw = {k: v for k, v in kw.items() if v is not None}
            for attempt in range(3):  # the free tier rate-limits; wait a little instead of giving up
                try:
                    text = self._call(self._groq_client(), g["model"], messages, **kw)
                    break
                except RateLimitError:
                    if attempt == 2:
                        raise
                    time.sleep(4 * (attempt + 1))
        if not text or (validate is not None and not validate(text)):
            raise UnusableOutput(f"{name} returned unusable output")
        return text

    def chat(self, messages: list[dict], validate=None, prefer: str | None = None, **kw) -> tuple[str, str]:
        """Return (text, provider). `validate(text) -> bool` marks output unusable. The `prefer`red provider
        (default: llm.prefer in config.yaml, else local) goes first; the other is the failsafe. Every fallback is logged."""
        first = prefer or self.cfg.get("prefer", "local")
        second = "groq" if first == "local" else "local"
        try:
            return self._run(first, messages, validate, **kw), first
        except Exception as e:  # unreachable, timeout, server error, unusable output
            reason = str(e) if isinstance(e, UnusableOutput) else f"{type(e).__name__}: {e}"
        log.warning("FALLBACK %s -> %s (%s)", first, second, reason)
        try:
            return self._run(second, messages, validate, **kw), second
        except UnusableOutput as e:
            raise RuntimeError(f"{first} failed ({reason}) and {e} as well") from e
        except RuntimeError as e:
            if "GROQ_API_KEY" in str(e):
                raise RuntimeError(f"{first} failed ({reason}) and GROQ_API_KEY is not set in .env") from e
            raise
