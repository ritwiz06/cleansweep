from types import SimpleNamespace

import pytest

from cleansweep.llm.client import LLMClient, LLMError, parse_json_text


class Err(Exception):
    def __init__(self, status, msg="err"):
        super().__init__(msg)
        self.status_code = status


class FakeOpenAI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.kwargs = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=usage
        )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("cleansweep.llm.client.time.sleep", lambda s: None)


def client(replies, tmp_path=None):
    cache = str(tmp_path / "c.sqlite") if tmp_path else None
    fake = FakeOpenAI(replies)
    return LLMClient("m", cache_path=cache, openai_client=fake), fake


def test_cache_hit_is_not_a_call(tmp_path):
    llm, fake = client(["hi"], tmp_path)
    msgs = [{"role": "user", "content": "x"}]
    assert llm.chat(msgs) == "hi"
    assert llm.chat(msgs) == "hi"
    assert len(fake.kwargs) == 1
    usage = llm.usage()
    assert {k: usage[k] for k in ("llm_calls", "prompt_tokens", "completion_tokens")} == {
        "llm_calls": 1,
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }
    assert usage["llm_retries"] == usage["llm_failures"] == 0


def test_retry_on_429():
    llm, fake = client([Err(429), Err(503), "done"])
    assert llm.chat([{"role": "user", "content": "x"}]) == "done"
    assert len(fake.kwargs) == 3


def test_seed_fallback():
    llm, fake = client([Err(400, "seed not supported"), "ok", "ok2"])
    assert llm.chat([{"role": "user", "content": "a"}], seed=1) == "ok"
    assert "seed" not in fake.kwargs[1]
    llm.chat([{"role": "user", "content": "b"}], seed=1)
    assert "seed" not in fake.kwargs[2]


def test_chat_json_strips_fences_and_retries():
    llm, _ = client(['```json\n{"a": 1}\n```'])
    assert llm.chat_json([{"role": "user", "content": "x"}]) == {"a": 1}
    llm, fake = client(["not json", "[1, 2]"])
    assert llm.chat_json([{"role": "user", "content": "x"}]) == [1, 2]
    assert len(fake.kwargs) == 2


def test_parse_json_text_with_chatter():
    assert parse_json_text('Sure! [{"x": 1}]') == [{"x": 1}]


def test_get_client_uses_config_timeout_and_no_sdk_retries(monkeypatch, tmp_path):
    import openai

    from cleansweep.core.config import load_config
    from cleansweep.llm.client import get_client

    seen = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: seen.update(kw) or object())
    monkeypatch.setenv("VOYAGER_API_KEY", "test-key")
    monkeypatch.setenv("VOYAGER_MODEL", "m")
    cfg = {**load_config()["core"]["llm"], "cache_path": str(tmp_path / "c.sqlite")}
    get_client(cfg)
    assert seen["timeout"] == 600
    assert seen["max_retries"] == 0


def test_extra_body_is_sent_and_kept_apart_in_the_cache(tmp_path):
    llm, fake = client(["plain", "fast"], tmp_path)
    msgs = [{"role": "user", "content": "x"}]
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    assert llm.chat(msgs) == "plain"
    assert llm.chat(msgs, extra_body=off) == "fast"
    assert "extra_body" not in fake.kwargs[0] and fake.kwargs[1]["extra_body"] == off
    assert llm.chat(msgs, extra_body=off) == "fast" and len(fake.kwargs) == 2


def test_client_extra_body_applies_to_every_request():
    fake = FakeOpenAI(["a"])
    llm = LLMClient("m", openai_client=fake, extra_body={"x": 1})
    llm.chat([{"role": "user", "content": "q"}], extra_body={"y": 2})
    assert fake.kwargs[0]["extra_body"] == {"x": 1, "y": 2}


PAGE = "<!DOCTYPE html>\n<html><head><title>example.com | 524: A timeout occurred</title>"


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


def test_524_is_retried_twice_then_fails_with_a_short_message():
    llm, fake = client([Err(524, PAGE), Err(524, PAGE), "done"])
    assert llm.chat([{"role": "user", "content": "x"}]) == "done"
    assert llm.usage()["llm_retries"] == 2
    llm, fake = client([Err(524, PAGE)] * 3)
    with pytest.raises(LLMError) as err:
        llm.chat([{"role": "user", "content": "x"}])
    assert len(fake.kwargs) == 3  # the request and 2 retries
    assert err.value.status_code == 524 and "<html>" not in str(err.value)
    assert "524: A timeout occurred" in str(err.value)
    usage = llm.usage()
    assert usage["llm_retries"] == 2 and usage["llm_failures"] == 1
    assert [e["event"] for e in usage["llm_events"]] == ["retry", "retry", "failure"]


def test_other_5xx_and_dropped_connections_are_retried():
    llm, fake = client([Err(500), APIConnectionError("reset"), "ok"])
    assert llm.chat([{"role": "user", "content": "x"}]) == "ok"
    assert len(fake.kwargs) == 3


def test_timeouts_and_client_errors_are_not_retried():
    for error in (APITimeoutError("Request timed out."), Err(400, "bad request")):
        llm, fake = client([error, "never"])
        with pytest.raises(LLMError):
            llm.chat([{"role": "user", "content": "x"}])
        assert len(fake.kwargs) == 1
        assert llm.usage()["llm_failures"] == 1


def test_chat_json_retry_and_failure_are_recorded():
    llm, fake = client(["not json", "[1]"])
    assert llm.chat_json([{"role": "user", "content": "x"}]) == [1]
    assert (
        fake.kwargs[1]["messages"][-1]["content"]
        == "That was not valid JSON. Return valid JSON only."
    )
    assert [e["event"] for e in llm.usage()["llm_events"]] == ["json_retry"]
    llm, _ = client(["bad", "still bad"])
    with pytest.raises(ValueError):
        llm.chat_json([{"role": "user", "content": "x"}])
    usage = llm.usage()
    assert usage["llm_retries"] == 1 and usage["llm_failures"] == 1


def test_max_calls_stops_new_requests_but_not_cache_hits(tmp_path):
    fake = FakeOpenAI(["a", "b", "c"])
    client = LLMClient("m", openai_client=fake, cache_path=str(tmp_path / "c.sqlite"), max_calls=2)
    assert client.chat([{"role": "user", "content": "1"}]) == "a"
    assert client.chat([{"role": "user", "content": "2"}]) == "b"
    assert client.chat([{"role": "user", "content": "1"}]) == "a"  # cached: free
    with pytest.raises(LLMError, match="budget exhausted"):
        client.chat([{"role": "user", "content": "3"}])
    assert client.usage()["llm_calls"] == 2 and len(fake.kwargs) == 2
