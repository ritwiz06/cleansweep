"""The one door to the LLM: redacts every message, enforces budgets, logs every request."""

from __future__ import annotations

import threading
import time

from .budgets import BudgetExhausted, RunBudget

_local = threading.local()


def acting(agent: str, budget=None):
    """Context manager: LLM requests in this thread are charged to `agent` (and its budget)."""

    class _Acting:
        def __enter__(self):
            self.prev = getattr(_local, "agent", None), getattr(_local, "budget", None)
            _local.agent, _local.budget = agent, budget

        def __exit__(self, *exc):
            _local.agent, _local.budget = self.prev

    return _Acting()


def current_agent() -> str | None:
    return getattr(_local, "agent", None)


class AgentLLM:
    """Wraps an LLM client (LLMClient, FakeLLM or ScriptedLLM) for the agent team.

    Every message passes through the redactor; each request is charged to the run budget and
    the acting agent's budget; at most `parallel` requests run at once; llm_start and llm_end
    events name the agent."""

    def __init__(
        self, llm, redact, log=None, run_budget: RunBudget | None = None, parallel: int = 3
    ):
        self.inner = llm
        self.model = getattr(llm, "model", None)
        self.redact = redact
        self.log = log
        self.run_budget = run_budget or RunBudget()
        self._slots = threading.Semaphore(max(1, parallel))
        self._lock = threading.Lock()
        self.n = 0
        self.by_agent: dict[str, int] = {}
        self.sent: list[list[dict]] = []  # redacted messages, for tests and audits

    def _clean(self, messages: list[dict]) -> list[dict]:
        return [{**m, "content": self.redact(m.get("content") or "")} for m in messages]

    def _call(self, method: str, messages, temperature, seed, extra_body):
        agent = current_agent() or "unknown"
        budget = getattr(_local, "budget", None)
        if budget is not None:
            budget.charge_llm()
        self.run_budget.take_llm_call()
        clean = self._clean(messages)
        with self._lock:
            self.n += 1
            n = self.n
            self.by_agent[agent] = self.by_agent.get(agent, 0) + 1
            self.sent.append(clean)
        if self.log is not None:
            self.log.emit("llm_start", agent=agent, payload={"n": n})
        start = time.time()
        ok = False
        try:
            with self._slots:
                reply = getattr(self.inner, method)(clean, temperature, seed, extra_body)
            ok = True
            return reply
        finally:
            if self.log is not None:
                self.log.emit(
                    "llm_end",
                    agent=agent,
                    payload={"n": n, "seconds": round(time.time() - start, 1), "ok": ok},
                )

    def chat(self, messages, temperature=0.0, seed=None, extra_body=None) -> str:
        return self._call("chat", messages, temperature, seed, extra_body)

    def chat_json(self, messages, temperature=0.0, seed=None, extra_body=None):
        return self._call("chat_json", messages, temperature, seed, extra_body)

    def usage(self) -> dict:
        usage = dict(self.inner.usage()) if hasattr(self.inner, "usage") else {}
        usage["requests"] = self.n
        usage["by_agent"] = dict(self.by_agent)
        return usage


__all__ = ["AgentLLM", "BudgetExhausted", "acting", "current_agent"]
