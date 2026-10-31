"""Stub of the agents package: the contract's names with no real work (CLEANSWEEP_STUBS=agents)."""

from __future__ import annotations

from datetime import UTC, datetime

from cleansweep.core.models import CleanupPlan, SweepReport


def run_agentic(target: str, cfg: dict, seed: int = 0, on_event=None) -> SweepReport:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    repo_id = f"local:{target.rstrip('/').split('/')[-1]}"
    return SweepReport(
        repo_id, "agentic", "now", seed, now, now, CleanupPlan(repo_id, now, []), [], {}
    )


def clean_project(
    path: str, cfg: dict, out: str | None = None, mode: str | None = None, dry_run: bool = False
) -> dict:
    return {"out": out, "workspace": None, "branch": None, "summary": {}, "files": []}


class MessageBoard:
    def __init__(self, log=None, broadcast: bool = False):
        self.messages: list = []

    def post(
        self, type: str, sender: str, body: dict, recipients=None, artifacts=None, parent=None
    ):
        return None

    def inbox(self, agent: str, type: str | None = None) -> list:
        return []


class ArtifactCache:
    def __init__(self, root, redact=None):
        self.items: dict = {}

    def put(self, kind: str, content) -> str:
        art_id = f"art:{kind}:{len(self.items):08d}"
        self.items[art_id] = content
        return art_id

    def get(self, art_id: str):
        return self.items[art_id]


class EventLog:
    def __init__(self, path=None, run_id: str = "", on_event=None, v1_hook=None, redact=None):
        self.events: list = []

    def emit(
        self,
        kind: str,
        agent=None,
        payload=None,
        recipients=None,
        artifacts=None,
        parent=None,
        phase=None,
    ) -> dict:
        event = {"kind": kind, "agent": agent, "payload": payload or {}}
        self.events.append(event)
        return event


class PhaseMachine:
    def __init__(self, log=None):
        self.phase = "ONBOARD"

    def go(self, to: str, reason: str) -> None:
        self.phase = to


def scan_secrets(repo_dir: str) -> dict:
    return {"files": [], "findings": [], "values": set()}


class Redactor:
    def __init__(self, values=None):
        pass

    def __call__(self, text: str) -> str:
        return text
