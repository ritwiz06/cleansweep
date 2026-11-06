"""Event log, schema v2: one JSON line per event, a superset of v1's live events."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

KINDS = {
    "run_start",
    "run_end",
    "phase_change",
    "thought",
    "tool_call",
    "tool_result",
    "message",
    "decision",
    "check",
    "budget",
    "lesson",
    "llm_start",
    "llm_end",
    "log",
}
SQUADS = {
    "manager": "manager",
    "explorer": "research",
    "auditor": "research",
    "investigator": "research",
    "planner": "research",
    "engineer": "development",
    "tester": "development",
    "validator": "development",
    "fixer": "development",
    "reporter": "development",
    "solo": "single",
}


def squad_of(agent: str | None) -> str | None:
    """Squad of an agent name such as "investigator#2"."""
    return SQUADS.get((agent or "").split("#")[0]) if agent else None


class EventLog:
    """Writes v2 events to events.jsonl (when a path is given) and passes them on.

    on_event gets each v2 event dict; v1_hook(name, payload) gets the v1 step events
    (open, analyze, plan, rank, batch, baseline, check_start, check, guard, report), so v1
    readers keep working on an agentic run. redact cleans every string before it is written."""

    def __init__(
        self,
        path: str | Path | None = None,
        run_id: str = "",
        on_event: Callable[[dict], None] | None = None,
        v1_hook: Callable[[str, dict], None] | None = None,
        redact: Callable[[str], str] | None = None,
        append: bool = False,
    ):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.on_event = on_event
        self.v1_hook = v1_hook
        self.redact = redact
        self.t0 = time.time()
        self.events: list[dict] = []
        self.phase: str | None = None
        self._lock = threading.Lock()
        self._n = 0
        if self.path and append and self.path.exists():  # a resumed run goes on with its log
            earlier = read_events(self.path)
            self._n = len(earlier)
            self.t0 -= earlier[-1]["t"] if earlier else 0.0
        elif self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def _clean(self, value):
        if self.redact is None:
            return value
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._clean(v) for v in value]
        return value

    def emit(
        self,
        kind: str,
        agent: str | None = None,
        payload: dict | None = None,
        recipients: list[str] | None = None,
        artifacts: list[str] | None = None,
        parent: str | None = None,
        phase: str | None = None,
    ) -> dict:
        """Record one event and return it."""
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        with self._lock:
            self._n += 1
            event = {
                "v": 2,
                "id": f"e{self._n:05d}",
                "parent": parent,
                "t": round(time.time() - self.t0, 3),
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "run_id": self.run_id,
                "agent": agent,
                "squad": squad_of(agent),
                "phase": phase or self.phase,
                "kind": kind,
                "recipients": list(recipients or []),
                "artifacts": list(artifacts or []),
                "payload": self._clean(payload or {}),
            }
            self.events.append(event)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, default=str) + "\n")
        if self.on_event:
            self.on_event(event)
        return event

    def v1(self, name: str, payload: dict) -> None:
        """Pass a v1 step event to the v1 hook, if any."""
        if self.v1_hook is not None:
            self.v1_hook(name, payload)


def read_events(path: str | Path) -> list[dict]:
    """Events of a recorded run, in order."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]
