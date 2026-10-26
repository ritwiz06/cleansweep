from __future__ import annotations

from .client import parse_json_text


class FakeLLM:
    """Offline stand-in for LLMClient: replies by substring match on the last user message."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.calls: list[list[dict]] = []

    def _reply(self, messages: list[dict]) -> str | None:
        self.calls.append(messages)
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        for key, reply in self.responses.items():
            if key in last:
                return reply
        return None

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        seed: int | None = None,
        extra_body: dict | None = None,
    ) -> str:
        reply = self._reply(messages)
        return "ok" if reply is None else reply

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        seed: int | None = None,
        extra_body: dict | None = None,
    ) -> dict | list:
        reply = self._reply(messages)
        return {} if reply is None else parse_json_text(reply)

    def usage(self) -> dict:
        return {"llm_calls": len(self.calls), "prompt_tokens": 0, "completion_tokens": 0}
