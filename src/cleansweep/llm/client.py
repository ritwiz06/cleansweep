from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
JSON_ONLY = "That was not valid JSON. Return valid JSON only."


class LLMError(RuntimeError):
    """A request that failed for good, with a short message (status and first line)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _short(exc: Exception) -> str:
    """Type, status and first line: a Cloudflare 524 page is HTML, not worth logging whole."""
    status = getattr(exc, "status_code", None)
    text = str(exc)
    title = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = " ".join(title.group(1).split()) if title else first
    return f"{type(exc).__name__}" + (f" {status}" if status else "") + f": {line[:200]}"


def _retryable(exc: Exception) -> bool:
    """Rate limits, server errors (Voyager's gateway sends 524) and dropped connections.
    A timeout is not retried: the request already took the whole timeout."""
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status == 429 or 500 <= status < 600
    return "connection" in type(exc).__name__.lower()


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
        max_retries: int = 2,
        timeout_s: float = 600,
        openai_client=None,
        extra_body: dict | None = None,
    ):
        if openai_client is None:
            from openai import OpenAI

            # our own loop retries; SDK retries would stack on top of it
            openai_client = OpenAI(
                base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0
            )
        self._client = openai_client
        self.model = model
        self.max_retries = max_retries
        self.extra_body = extra_body or None
        self._cache = _Cache(cache_path) if cache_path else None
        self._seed_ok = True
        self._usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self._events: list[dict] = []  # retries and failures, for the run stats

    def _event(self, kind: str, exc: Exception | None = None, attempt: int = 0) -> None:
        event = {"event": kind, "attempt": attempt}
        if exc is not None:
            event.update(status=getattr(exc, "status_code", None), error=_short(exc))
        self._events.append(event)
        log.warning("llm %s (attempt %d): %s", kind, attempt, event.get("error", ""))

    def _key(
        self, messages: list[dict], temperature: float, seed: int | None, extra: dict | None
    ) -> str:
        parts = [self.model, messages, temperature, seed] + ([extra] if extra else [])
        blob = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _create(
        self, messages: list[dict], temperature: float, seed: int | None, extra: dict | None
    ):
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature}
        if seed is not None and self._seed_ok:
            kwargs["seed"] = seed
        if extra:
            kwargs["extra_body"] = extra
        delay, attempt = 2.0, 0
        while True:
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == 400 and "seed" in kwargs and "seed" in str(exc).lower():
                    self._seed_ok = False
                    kwargs.pop("seed")
                    continue
                if not _retryable(exc) or attempt >= self.max_retries:
                    self._event("failure", exc, attempt)
                    raise LLMError(_short(exc), status) from exc
                attempt += 1
                self._event("retry", exc, attempt)
                time.sleep(delay)
                delay = min(delay * 2, 30)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        seed: int | None = None,
        extra_body: dict | None = None,
    ) -> str:
        """Send a chat request and return the reply text (cached on disk).

        extra_body adds provider options to this request, on top of the client's own."""
        extra = {**(self.extra_body or {}), **(extra_body or {})} or None
        key = self._key(messages, temperature, seed, extra)
        if self._cache and (hit := self._cache.get(key)) is not None:
            return hit
        resp = self._create(messages, temperature, seed, extra)
        reply = resp.choices[0].message.content or ""
        self._usage["llm_calls"] += 1
        if getattr(resp, "usage", None):
            self._usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            self._usage["completion_tokens"] += resp.usage.completion_tokens or 0
        if self._cache:
            self._cache.put(key, reply)
        return reply

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        seed: int | None = None,
        extra_body: dict | None = None,
    ) -> dict | list:
        """Like chat, but parse the reply as JSON; on malformed JSON, ask once more with a short
        "valid JSON only" follow-up."""
        messages = [
            *messages[:-1],
            {**messages[-1], "content": messages[-1]["content"] + "\n\nReply with JSON only."},
        ]
        reply = self.chat(messages, temperature, seed, extra_body)
        try:
            return parse_json_text(reply)
        except json.JSONDecodeError as exc:
            self._event("json_retry", exc)
            retry = [
                *messages,
                {"role": "assistant", "content": reply},
                {"role": "user", "content": JSON_ONLY},
            ]
            try:
                return parse_json_text(self.chat(retry, temperature, seed, extra_body))
            except json.JSONDecodeError as again:
                self._event("json_failure", again, 1)
                raise

    def usage(self) -> dict:
        """Calls and token counts so far (cache hits are not counted), plus the retries and
        failures: counts and one record per event."""
        events = [dict(e) for e in self._events]
        return {
            **self._usage,
            "llm_retries": sum(e["event"] in ("retry", "json_retry") for e in events),
            "llm_failures": sum(e["event"] in ("failure", "json_failure") for e in events),
            "llm_events": events,
        }


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
        max_retries=cfg.get("max_retries", 2),
        timeout_s=cfg.get("timeout_s", 600),
        extra_body=cfg.get("extra_body"),
    )
