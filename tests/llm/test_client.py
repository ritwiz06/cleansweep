from types import SimpleNamespace

import pytest

from cleansweep.llm.client import LLMClient, parse_json_text


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
    assert llm.usage() == {"llm_calls": 1, "prompt_tokens": 10, "completion_tokens": 5}


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
