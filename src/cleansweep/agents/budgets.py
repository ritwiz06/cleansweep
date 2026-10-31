"""Step, LLM-call and time budgets: per agent instance and for the whole run."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

RUN_KEYS = {"llm": "llm_calls", "minutes": "minutes", "tests": "test_runs"}


class BudgetExhausted(RuntimeError):
    """Raised when a budget has no room left for the next step or LLM call."""


@dataclass
class Budget:
    """One agent instance's budget. Zero or less means no limit for that measure."""

    steps: int = 0
    llm_calls: int = 0
    seconds: float = 0
    used_steps: int = 0
    used_llm: int = 0
    started: float = field(default_factory=time.time)

    @classmethod
    def from_cfg(cls, cfg: dict | None) -> Budget:
        cfg = cfg or {}
        return cls(
            int(cfg.get("steps", 0)), int(cfg.get("llm_calls", 0)), float(cfg.get("seconds", 0))
        )

    def exhausted(self) -> str | None:
        """The limit that is used up, or None."""
        if self.steps > 0 and self.used_steps >= self.steps:
            return f"step budget ({self.steps}) used up"
        if self.llm_calls > 0 and self.used_llm >= self.llm_calls:
            return f"LLM-call budget ({self.llm_calls}) used up"
        if self.seconds > 0 and time.time() - self.started >= self.seconds:
            return f"time budget ({self.seconds:.0f} s) used up"
        return None

    def charge_step(self) -> None:
        why = self.exhausted()
        if why:
            raise BudgetExhausted(why)
        self.used_steps += 1

    def charge_llm(self) -> None:
        why = self.exhausted()
        if why:
            raise BudgetExhausted(why)
        self.used_llm += 1

    def summary(self) -> dict:
        return {
            "steps": self.used_steps,
            "llm_calls": self.used_llm,
            "seconds": round(time.time() - self.started, 1),
        }


class RunBudget:
    """The whole run's caps (`--budget`): LLM calls, minutes and test runs. Thread-safe."""

    def __init__(self, llm_calls: int = 0, minutes: float = 0, test_runs: int = 0):
        self.llm_calls, self.minutes, self.test_runs = llm_calls, minutes, test_runs
        self.used_llm = 0
        self.started = time.time()
        self._lock = threading.Lock()

    @classmethod
    def from_cfg(cls, cfg: dict | None) -> RunBudget:
        cfg = cfg or {}
        return cls(
            int(cfg.get("llm_calls", 0)), float(cfg.get("minutes", 0)), int(cfg.get("test_runs", 0))
        )

    def take_llm_call(self) -> None:
        with self._lock:
            if self.llm_calls > 0 and self.used_llm >= self.llm_calls:
                raise BudgetExhausted(f"run LLM-call budget ({self.llm_calls}) used up")
            self.used_llm += 1

    def out_of_time(self) -> bool:
        return self.minutes > 0 and time.time() - self.started >= self.minutes * 60

    def out_of_tests(self, used: int) -> bool:
        return self.test_runs > 0 and used >= self.test_runs

    def as_dict(self) -> dict:
        return {"llm_calls": self.llm_calls, "minutes": self.minutes, "test_runs": self.test_runs}


def parse_budget(text: str) -> dict:
    """Parse `--budget llm=150,minutes=60,tests=80` into run-budget settings."""
    out: dict = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        key, sep, value = part.partition("=")
        if not sep or key.strip() not in RUN_KEYS:
            raise ValueError(f"unknown budget item {part!r}; use llm=N, minutes=N or tests=N")
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"budget {key.strip()} needs a number, got {value!r}") from None
        if number <= 0:
            raise ValueError(f"budget {key.strip()} must be positive, got {value}")
        out[RUN_KEYS[key.strip()]] = number if key.strip() == "minutes" else int(number)
    return out
