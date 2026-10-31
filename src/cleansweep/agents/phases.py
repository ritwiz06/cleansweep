"""The Manager's phase machine: forward steps, limited steps back, and an early stop."""

from __future__ import annotations

import time

PHASES = [
    "ONBOARD",
    "BASELINE",
    "AUDIT",
    "INVESTIGATE",
    "PLAN",
    "EXECUTE",
    "FINAL_VERIFY",
    "REPORT",
    "DONE",
]
# steps back and how often each may be taken in one run
BACK = {("BASELINE", "ONBOARD"): 1, ("EXECUTE", "PLAN"): 2, ("FINAL_VERIFY", "EXECUTE"): 1}
# v1 stage that starts with each phase, for v1 readers of the event log
V1_STAGE = {
    "ONBOARD": "open",
    "BASELINE": "analyze",
    "AUDIT": "plan",
    "EXECUTE": "guard",
    "REPORT": "done",
}


class PhaseError(RuntimeError):
    """An illegal phase change."""


class PhaseMachine:
    """Tracks the current phase, each phase's time and the steps back taken."""

    def __init__(self, log=None):
        self.log = log
        self.phase = "ONBOARD"
        self.started = time.time()
        self.history: list[dict] = [{"phase": "ONBOARD", "start": 0.0, "end": None}]
        self.back_steps: dict[str, int] = {}
        self.t0 = time.time()
        if log is not None:
            log.phase = self.phase

    def can_go_back(self, to: str) -> bool:
        key = (self.phase, to)
        return key in BACK and self.back_steps.get(f"{key[0]}->{key[1]}", 0) < BACK[key]

    def go(self, to: str, reason: str) -> None:
        """Move to another phase: the next one, REPORT/DONE early, or an allowed step back."""
        if to not in PHASES:
            raise PhaseError(f"unknown phase {to}")
        here, there = PHASES.index(self.phase), PHASES.index(to)
        back = there < here
        if back:
            if not self.can_go_back(to):
                raise PhaseError(f"no step back from {self.phase} to {to} left")
            key = f"{self.phase}->{to}"
            self.back_steps[key] = self.back_steps.get(key, 0) + 1
        elif there == here or (there > here + 1 and to not in ("REPORT", "DONE")):
            raise PhaseError(f"cannot go from {self.phase} to {to}")
        now = round(time.time() - self.t0, 3)
        self.history[-1]["end"] = now
        old, self.phase = self.phase, to
        self.history.append({"phase": to, "start": now, "end": None})
        if self.log is not None:
            self.log.phase = to
            self.log.emit(
                "phase_change",
                agent="manager",
                payload={"from": old, "to": to, "reason": reason, "back": back},
            )

    def order(self) -> list[str]:
        """Phases in the order they were entered (repeats included)."""
        return [h["phase"] for h in self.history]

    def seconds(self) -> dict[str, float]:
        """Total seconds spent in each phase."""
        now = round(time.time() - self.t0, 3)
        out: dict[str, float] = {}
        for h in self.history:
            end = h["end"] if h["end"] is not None else now
            out[h["phase"]] = round(out.get(h["phase"], 0.0) + end - h["start"], 2)
        return out
