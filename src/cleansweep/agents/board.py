"""Message board: every message is a directed hyperedge (one sender, a set of recipients).

Each message type has a fixed schema, checked when the message is posted, and default
recipients. An agent reads only its own inbox. In the broadcast ablation every message goes
to every agent."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import jsonschema

AGENTS = [
    "manager",
    "explorer",
    "auditor",
    "investigator",
    "planner",
    "engineer",
    "tester",
    "validator",
    "fixer",
    "reporter",
]
S = {"type": "string"}
N = {"type": "number"}
INT = {"type": "integer"}
B = {"type": "boolean"}
STRS = {"type": "array", "items": S}


def _obj(required: dict, optional: dict | None = None) -> dict:
    props = {**required, **(optional or {})}
    return {"type": "object", "required": list(required), "properties": props}


SCHEMAS: dict[str, dict] = {
    "task": _obj(
        {"goal": S}, {"package": S, "kind": S, "items": STRS, "budget": {"type": "object"}}
    ),
    "brief": _obj(
        {"summary": S, "frameworks": STRS, "test_command": S},
        {
            "install_command": S,
            "entry_points": STRS,
            "languages": {"type": "object"},
            "ui_framework": {"type": ["string", "null"]},
            "secret_files": INT,
            "secret_findings": INT,
        },
    ),
    "baseline": _obj(
        {"ok": B, "passed": INT, "failed": INT, "errors": INT, "flaky": STRS, "failing": STRS},
        {"runs": INT},
    ),
    "candidates": _obj(
        {
            "items": {
                "type": "array",
                "items": _obj({"item_id": S, "unit": S, "category": S, "lane": S}),
            }
        },
    ),
    "verdict": _obj(
        {
            "item_id": S,
            "decision": {"enum": ["safe", "suggest", "drop"]},
            "reason": S,
            "evidence": {"type": "array"},
        },
        {"lessons_cited": STRS, "confidence": N},
    ),
    "blueprint": _obj({"packages": STRS}),
    "package_applied": _obj({"package": S, "applied": STRS, "not_applied": STRS}, {"commit": S}),
    "test_result": _obj({"package": S, "ok": B, "new_failures": STRS}, {"stage": S}),
    "validation": _obj(
        {"package": S, "ok": B},
        {
            "probes": {"type": ["object", "null"]},
            "coverage": {"type": ["number", "null"]},
            "checks": {"type": "object"},
        },
    ),
    "ui_baseline": _obj(
        {"ok": B}, {"classes": INT, "unstable": INT, "import_errors": INT, "reason": S}
    ),
    "failure": _obj({"package": S, "stage": S}),
    "repair": _obj(
        {"package": S, "outcome": {"enum": ["repaired", "rolled_back", "split", "retry"]}},
        {"turns": INT},
    ),
    "lesson": _obj({"lesson_id": S, "pattern": {"type": "object"}, "reason": S}),
    "final_check": _obj({"ok": B, "new_failures": STRS}, {"passed": INT, "baseline_passed": INT}),
    "report": _obj({"files": STRS}),
}
ROUTES: dict[str, list[str]] = {
    "task": [],  # always addressed to one agent
    "brief": ["manager", "tester", "auditor", "planner", "validator"],
    "baseline": ["manager", "planner", "validator", "fixer"],
    "candidates": ["manager", "investigator"],
    "verdict": ["manager", "planner"],
    "blueprint": ["manager", "engineer", "tester", "validator", "reporter"],
    "package_applied": ["manager", "tester", "validator"],
    "test_result": ["manager", "validator", "fixer"],
    "validation": ["manager", "fixer", "reporter"],
    "ui_baseline": ["manager", "reporter"],
    "failure": ["fixer"],
    "repair": ["manager", "engineer", "reporter"],
    "lesson": ["manager", "auditor", "investigator", "planner"],
    "final_check": ["manager", "reporter"],
    "report": ["manager"],
}


@dataclass
class Message:
    msg_id: str
    type: str
    sender: str
    recipients: list[str]
    body: dict
    artifacts: list[str] = field(default_factory=list)
    parent: str | None = None
    t: float = 0.0


def role(agent: str) -> str:
    """ "investigator#2" -> "investigator"."""
    return agent.split("#")[0]


class MessageBoard:
    """Stores every message; delivers each only to its recipients (or to all, broadcast)."""

    def __init__(self, log=None, broadcast: bool = False):
        self.log = log
        self.broadcast = broadcast
        self.messages: list[Message] = []
        self._lock = threading.Lock()
        self.t0 = time.time()

    def post(
        self,
        type: str,
        sender: str,
        body: dict,
        recipients: list[str] | None = None,
        artifacts: list[str] | None = None,
        parent: str | None = None,
    ) -> Message:
        """Validate a message against its type's schema and deliver it."""
        if type not in SCHEMAS:
            raise ValueError(f"unknown message type {type!r}")
        jsonschema.validate(body, SCHEMAS[type])
        to = list(recipients) if recipients is not None else list(ROUTES[type])
        if not to:
            raise ValueError(f"a {type} message needs recipients")
        if self.broadcast:
            to = [a for a in AGENTS if a != role(sender)]
        with self._lock:
            msg = Message(
                f"m{len(self.messages) + 1:04d}",
                type,
                sender,
                to,
                body,
                list(artifacts or []),
                parent,
                round(time.time() - self.t0, 3),
            )
            self.messages.append(msg)
        if self.log is not None:
            self.log.emit(
                "message",
                agent=sender,
                recipients=to,
                artifacts=msg.artifacts,
                payload={"msg_id": msg.msg_id, "type": type, "body": body, "parent": parent},
            )
        return msg

    def inbox(self, agent: str, type: str | None = None) -> list[Message]:
        """Messages addressed to an agent (its role), optionally of one type."""
        name = role(agent)
        with self._lock:
            return [
                m
                for m in self.messages
                if name in m.recipients and (type is None or m.type == type)
            ]

    def latest(self, agent: str, type: str) -> Message | None:
        found = self.inbox(agent, type)
        return found[-1] if found else None

    def hyperedges(self) -> list[tuple[str, tuple[str, ...]]]:
        """(sender, recipients) of every message, in order."""
        return [(m.sender, tuple(m.recipients)) for m in self.messages]
