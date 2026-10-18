import logging
from types import SimpleNamespace

import pytest

from src.llm import LLMClient

CFG = {
    "local": {"base_url": "http://localhost:1", "model": "m-local", "timeout_s": 1},
    "groq": {"base_url": "http://localhost:2", "model": "m-groq", "timeout_s": 1},
    "temperature": 0.1,
    "max_tokens": 10,
}
MSG = [{"role": "user", "content": "hi"}]


def fake(result):
    """Fake OpenAI client whose completion returns `result` or raises it."""
    def create(**_):
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def make(local, groq, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    c = LLMClient(CFG)
    c.local = fake(local)
    c.groq = fake(groq)
    return c


def test_local_used_when_ok(monkeypatch):
    assert make("local answer", "groq answer", monkeypatch).chat(MSG) == ("local answer", "local")


def test_fallback_when_unreachable_and_logged(monkeypatch, caplog):
    c = make(ConnectionError("down"), "groq answer", monkeypatch)
    with caplog.at_level(logging.WARNING, logger="supportrag.llm"):
        assert c.chat(MSG) == ("groq answer", "groq")
    assert "FALLBACK" in caplog.text


def test_fallback_on_empty_output(monkeypatch):
    assert make("  ", "groq answer", monkeypatch).chat(MSG)[1] == "groq"


def test_fallback_on_failed_validation(monkeypatch):
    c = make("not json", "{}", monkeypatch)
    assert c.chat(MSG, validate=lambda t: t.startswith("{"))[1] == "groq"


def test_no_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = LLMClient(CFG)
    c.local = fake(TimeoutError("slow"))
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        c.chat(MSG)
