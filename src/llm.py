"""One small LLM client: LM Studio (local) first, Groq as failsafe.

Fallback happens only if the local server is unreachable, times out, or
returns unusable output. Every fallback is logged.
"""
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

log = logging.getLogger("supportrag.llm")


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
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=kw.get("temperature", self.cfg["temperature"]),
            max_tokens=kw.get("max_tokens", self.cfg["max_tokens"]),
        )
        return (resp.choices[0].message.content or "").strip()

    def chat(self, messages: list[dict], validate=None, **kw) -> tuple[str, str]:
        """Return (text, provider). `validate(text) -> bool` marks output unusable."""
        try:
            text = self._call(self.local, self.cfg["local"]["model"], messages, **kw)
            if text and (validate is None or validate(text)):
                return text, "local"
            reason = "unusable output"
        except Exception as e:  # unreachable, timeout, server error
            reason = f"{type(e).__name__}: {e}"
        log.warning("FALLBACK local -> groq (%s)", reason)

        if self.groq is None:
            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise RuntimeError("Local LLM failed and GROQ_API_KEY is not set in .env")
            self.groq = OpenAI(
                base_url=self.cfg["groq"]["base_url"],
                api_key=key,
                timeout=self.cfg["groq"]["timeout_s"],
                max_retries=0,
            )
        text = self._call(self.groq, self.cfg["groq"]["model"], messages, **kw)
        if not text or (validate is not None and not validate(text)):
            raise RuntimeError("Groq returned unusable output as well")
        return text, "groq"
