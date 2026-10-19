from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

RETRY_STATUS = {429, 500, 502, 503, 504}
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_text(text: str) -> dict | list:
    """Parse a model reply as JSON, tolerating code fences and leading chatter."""
    cleaned = FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        return json.loads(cleaned[start:])


class _Cache:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, reply TEXT)")

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT reply FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, reply: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, reply))
        self.db.commit()


class LLMClient:
    """Voyager (OpenAI-compatible) chat client with retries and a disk cache."""

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        cache_path: str | None = None,
        max_retries: int = 5,
        timeout_s: float = 120,
        openai_client=None,
    ):
        if openai_client is None:
            from openai import OpenAI

            openai_client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
        self._client = openai_client
        self.model = model
        self.max_retries = max_retries
        self._cache = _Cache(cache_path) if cache_path else None
        self._seed_ok = True
        self._usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _key(self, messages: list[dict], temperature: float, seed: int | None) -> str:
        blob = json.dumps([self.model, messages, temperature, seed], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _create(self, messages: list[dict], temperature: float, seed: int | None):
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature}
        if seed is not None and self._seed_ok:
            kwargs["seed"] = seed
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == 400 and "seed" in kwargs and "seed" in str(exc).lower():
                    self._seed_ok = False
                    kwargs.pop("seed")
                    continue
                retryable = status in RETRY_STATUS or "timeout" in type(exc).__name__.lower()
                if not retryable or attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError("unreachable")

    def chat(self, messages: list[dict], temperature: float = 0.0, seed: int | None = None) -> str:
        """Send a chat request and return the reply text (cached on disk)."""
        key = self._key(messages, temperature, seed)
        if self._cache and (hit := self._cache.get(key)) is not None:
            return hit
        resp = self._create(messages, temperature, seed)
        reply = resp.choices[0].message.content or ""
        self._usage["llm_calls"] += 1
        if getattr(resp, "usage", None):
            self._usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            self._usage["completion_tokens"] += resp.usage.completion_tokens or 0
        if self._cache:
            self._cache.put(key, reply)
        return reply

    def chat_json(
        self, messages: list[dict], temperature: float = 0.0, seed: int | None = None
    ) -> dict | list:
        """Like chat, but parse the reply as JSON; retry once with a reminder."""
        messages = [
            *messages[:-1],
            {**messages[-1], "content": messages[-1]["content"] + "\n\nReply with JSON only."},
        ]
        reply = self.chat(messages, temperature, seed)
        try:
            return parse_json_text(reply)
        except json.JSONDecodeError:
            retry = [
                *messages,
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "That was not valid JSON. Return valid JSON only."},
            ]
            return parse_json_text(self.chat(retry, temperature, seed))

    def usage(self) -> dict:
        """Calls and token counts so far (cache hits are not counted)."""
        return dict(self._usage)


def get_client(cfg: dict | None = None) -> LLMClient:
    """Build the Voyager client from config and environment (.env is loaded by load_config)."""
    cfg = cfg or {}
    model_env = (
        cfg.get("alt_model_env", "VOYAGER_MODEL_ALT")
        if cfg.get("alt")
        else cfg.get("model_env", "VOYAGER_MODEL")
    )
    model = os.environ.get(model_env)
    api_key = os.environ.get(cfg.get("api_key_env", "VOYAGER_API_KEY"))
    if not model or not api_key:
        raise RuntimeError(f"set {model_env} and VOYAGER_API_KEY in .env to use the LLM")
    return LLMClient(
        model=model,
        base_url=os.environ.get(cfg.get("base_url_env", "VOYAGER_BASE_URL")),
        api_key=api_key,
        cache_path=cfg.get("cache_path", ".cleansweep/llm_cache.sqlite"),
        max_retries=cfg.get("max_retries", 5),
        timeout_s=cfg.get("timeout_s", 120),
    )
