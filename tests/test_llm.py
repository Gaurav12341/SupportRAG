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


def raw(content, usage=None, headers=None):
    """What `client.chat.completions.with_raw_response.create` returns: .parse() and .headers."""
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                           usage=SimpleNamespace(**(usage or {})))
    return SimpleNamespace(parse=lambda: resp, headers=headers or {})


def client_of(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))))


def fake(result):
    """Fake OpenAI client whose completion returns `result` or raises it."""
    def create(**_):
        if isinstance(result, Exception):
            raise result
        return raw(result)
    return client_of(create)


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


def test_prefer_groq_goes_first_and_local_is_the_failsafe(monkeypatch, caplog):
    c = make("local answer", "groq answer", monkeypatch)
    assert c.chat(MSG, prefer="groq") == ("groq answer", "groq")
    c = make("local answer", ConnectionError("down"), monkeypatch)
    with caplog.at_level(logging.WARNING, logger="supportrag.llm"):
        assert c.chat(MSG, prefer="groq") == ("local answer", "local")
    assert "FALLBACK groq -> local" in caplog.text


def test_prefer_groq_without_key_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = LLMClient(CFG)
    c.local = fake("local answer")
    assert c.chat(MSG, prefer="groq") == ("local answer", "local")


def test_config_prefer_is_the_default_order(monkeypatch):
    c = make("local answer", "groq answer", monkeypatch)
    c.cfg = {**CFG, "prefer": "groq"}
    assert c.chat(MSG)[1] == "groq"


def test_groq_gets_its_own_token_and_reasoning_settings(monkeypatch):
    seen = {}

    def create(**kw):
        seen.update(kw)
        return raw("ok")

    c = make("x", "y", monkeypatch)
    c.cfg = {**CFG, "groq": {**CFG["groq"], "max_tokens": 1500, "reasoning_effort": "low"}}
    c.groq = client_of(create)
    assert c.chat(MSG, prefer="groq") == ("ok", "groq")
    assert seen["max_tokens"] == 1500 and seen["reasoning_effort"] == "low"


# ---------- cache, usage, no-fallback ----------

USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def counting(content, usage=USAGE):
    calls = []

    def create(**kw):
        calls.append(kw)
        return raw(content, usage, {"x-ratelimit-remaining-tokens": "7000"})
    return client_of(create), calls


@pytest.fixture
def cfg(tmp_path):
    return {**CFG, "cache_dir": str(tmp_path), "groq": {**CFG["groq"], "limits": {
        "requests_per_min": 30, "requests_per_day": 1000, "tokens_per_min": 8000, "tokens_per_day": 200000}}}


def test_cached_reply_is_not_requested_twice_and_keeps_its_usage(monkeypatch, cfg, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    import src.llm as L
    monkeypatch.setattr(L, "ROOT", tmp_path.parent)  # caches live under tmp_path
    monkeypatch.setattr(L, "_caches", {})
    c = LLMClient(cfg)
    c.local, calls = counting("hello")
    first = c.chat_full(MSG, cache="t")
    second = c.chat_full(MSG, cache="t")
    assert len(calls) == 1 and not first.cached and second.cached and second.text == "hello"
    assert second.usage["total_tokens"] == 15
    other = c.chat_full([{"role": "user", "content": "different"}], cache="t")
    assert len(calls) == 2 and not other.cached
    assert c.usage_by_model()["local/m-local"] == {"calls": 3, "cached_calls": 1, "prompt_tokens": 30,
                                                   "completion_tokens": 15, "total_tokens": 45,
                                                   "fresh_total_tokens": 30}


def test_cache_survives_a_new_client_and_salt_forces_a_fresh_call(monkeypatch, cfg, tmp_path):
    import src.llm as L
    monkeypatch.setattr(L, "ROOT", tmp_path.parent)
    monkeypatch.setattr(L, "_caches", {})
    a = LLMClient(cfg)
    a.local, calls = counting("x")
    a.chat_full(MSG, cache="t")
    monkeypatch.setattr(L, "_caches", {})  # a new process reads the file
    b = LLMClient(cfg)
    b.local, calls_b = counting("y")
    assert b.chat_full(MSG, cache="t").text == "x" and not calls_b
    assert b.chat_full(MSG, cache="t", salt="run2").text == "y" and len(calls_b) == 1


def test_no_fallback_raises_instead_of_switching_provider(monkeypatch):
    c = make(ConnectionError("down"), "groq answer", monkeypatch)
    with pytest.raises(ConnectionError):
        c.chat(MSG, fallback=False)


def test_think_tags_are_stripped(monkeypatch):
    assert make("<think>hmm</think>\n{\"a\": 1}", "g", monkeypatch).chat(MSG)[0] == '{"a": 1}'


def test_groq_model_can_be_chosen_per_call(monkeypatch, cfg):
    seen = []
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    c = LLMClient(cfg)
    c.groq = client_of(lambda **kw: (seen.append(kw["model"]), raw("ok"))[1])
    assert c.chat_full(MSG, prefer="groq", model="other/model").model == "other/model"
    assert seen == ["other/model"]


# ---------- pacing ----------

from src.llm import Pacer, QuotaExhausted, UsageLedger  # noqa: E402

LIMITS = {"requests_per_min": 30, "requests_per_day": 1000, "tokens_per_min": 8000, "tokens_per_day": 200000}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def pacer(clock, ledger=None, limits=LIMITS):
    return Pacer("m", limits, ledger, clock=clock.now, sleep=clock.sleep)


def test_minute_token_bucket_makes_the_next_call_wait():
    clk = Clock()
    p = pacer(clk)
    p.before(3000)
    p.after({"total_tokens": 6000}, {})
    assert p.wait_needed(1000) == 0  # 2000 left
    wait = p.wait_needed(4000)  # needs 2000 more, which refill at 8000 / 60 per second
    assert 14 < wait < 17
    clk.t += 61
    assert p.wait_needed(4000) == 0


def test_server_header_overrides_a_too_optimistic_local_count():
    clk = Clock()
    p = pacer(clk)
    p.after({"total_tokens": 100}, {"x-ratelimit-remaining-tokens": "500"})
    assert p.wait_needed(2000) > 10


def test_request_per_minute_limit():
    clk = Clock()
    p = pacer(clk, limits={**LIMITS, "requests_per_min": 3})
    for _ in range(2):
        p.after({"total_tokens": 1}, {})
    assert p.wait_needed(10) > 50


def test_daily_token_budget_raises_and_survives_a_restart(tmp_path):
    clk = Clock()
    ledger = UsageLedger(tmp_path / "u.jsonl")
    p = pacer(clk, ledger, {**LIMITS, "tokens_per_day": 5000})
    p.after({"prompt_tokens": 3000, "completion_tokens": 1500, "total_tokens": 4500}, {}, "judge")
    with pytest.raises(QuotaExhausted):
        p.wait_needed(1000)
    again = pacer(clk, UsageLedger(tmp_path / "u.jsonl"), {**LIMITS, "tokens_per_day": 5000})  # new process, same ledger
    with pytest.raises(QuotaExhausted):
        again.wait_needed(1000)
    clk.t += 86400 + 1  # a day later it is free again
    assert pacer(clk, UsageLedger(tmp_path / "u.jsonl"), {**LIMITS, "tokens_per_day": 5000}).wait_needed(1000) == 0


class Err(Exception):
    def __init__(self, message, retry_after=None):
        self.message = message
        self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})


def test_429_per_minute_is_waited_out_and_per_day_stops():
    clk = Clock()
    p = pacer(clk)
    p.on_429(Err("Rate limit reached ... on tokens per minute (TPM): Limit 8000. Please try again in 3.5s."))
    assert clk.slept == [4.5]
    with pytest.raises(QuotaExhausted):
        p.on_429(Err("Rate limit reached ... on tokens per day (TPD): Limit 200000. Please try again in 8m12s."))
    with pytest.raises(QuotaExhausted):
        p.on_429(Err("some limit", retry_after="900"))


def test_quota_stop_propagates_without_fallback_and_a_rerun_resumes_from_the_cache(monkeypatch, cfg, tmp_path):
    """A daily-quota stop must not be swallowed by the local fallback in an eval, and what finished before it stays cached."""
    import src.llm as L
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(L, "ROOT", tmp_path.parent)
    monkeypatch.setattr(L, "_caches", {})
    monkeypatch.setattr(L, "_pacers", {})
    m1, m2 = [{"role": "user", "content": "one"}], [{"role": "user", "content": "two"}]
    c = LLMClient({**cfg, "groq": {**cfg["groq"], "usage_log": None}})
    c.groq, calls = counting("ok")
    assert c.chat_full(m1, prefer="groq", cache="q", fallback=False).text == "ok"
    monkeypatch.setattr(L.Pacer, "wait_needed", lambda self, n: (_ for _ in ()).throw(QuotaExhausted("daily limit")))
    with pytest.raises(QuotaExhausted):  # the second question hits the quota
        c.chat_full(m2, prefer="groq", cache="q", fallback=False)
    assert c.chat_full(m1, prefer="groq", cache="q", fallback=False).cached  # the first one is still free
    c.local = fake("local answer")  # with the failsafe allowed the pipeline (not the eval) falls back to local
    assert c.chat_full(m2, prefer="groq", fallback=True).provider == "local"
    monkeypatch.undo()  # a later run, quota available again: only the unfinished question is asked
    monkeypatch.setattr(L, "ROOT", tmp_path.parent)
    c2 = LLMClient({**cfg, "groq": {**cfg["groq"], "usage_log": None}})
    c2.groq, calls2 = counting("second")
    monkeypatch.setattr(L, "_caches", {})
    assert c2.chat_full(m1, prefer="groq", cache="q").cached and c2.chat_full(m2, prefer="groq", cache="q").text == "second"
    assert len(calls) == 1 and len(calls2) == 1
