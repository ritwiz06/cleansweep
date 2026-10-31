"""ScriptedLLM: an offline LLM that plays a script, for tests of the agent team."""

from __future__ import annotations

import json
import threading

from cleansweep.llm.client import parse_json_text


class ScriptedLLM:
    """Replies from a script. Each rule is (substring, replies): a request takes the next reply
    of the first rule whose substring appears in its messages (the last reply repeats).
    Requests no rule matches get `default`. Thread-safe; records every request."""

    model = "scripted"

    def __init__(
        self, rules: list[tuple[str, list[str] | str]] | None = None, default: str | None = None
    ):
        self.rules = [(key, [r] if isinstance(r, str) else list(r)) for key, r in (rules or [])]
        self.default = default if default is not None else json.dumps({"final": {}})
        self.positions = [0] * len(self.rules)
        self.calls: list[list[dict]] = []
        self._lock = threading.Lock()

    def _reply(self, messages: list[dict]) -> str:
        text = "\n".join(m.get("content") or "" for m in messages)
        with self._lock:
            self.calls.append(messages)
            for n, (key, replies) in enumerate(self.rules):
                if key in text:
                    reply = replies[min(self.positions[n], len(replies) - 1)]
                    self.positions[n] += 1
                    return reply
        return self.default

    def chat(self, messages, temperature=0.0, seed=None, extra_body=None) -> str:
        return self._reply(messages)

    def chat_json(self, messages, temperature=0.0, seed=None, extra_body=None):
        return parse_json_text(self._reply(messages))

    def usage(self) -> dict:
        return {
            "llm_calls": len(self.calls),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "llm_retries": 0,
            "llm_failures": 0,
            "llm_events": [],
        }


def tool(name: str, args: dict, thought: str = "check") -> str:
    """A scripted tool-call reply."""
    return json.dumps({"thought": thought, "tool": name, "args": args})


def final(answer: dict) -> str:
    """A scripted final reply."""
    return json.dumps({"final": answer})
