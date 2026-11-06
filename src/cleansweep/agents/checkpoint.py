"""Resume after an interruption. At each safe point (a phase entered, a work package finished)
the run's state goes to <out>/checkpoint.json; `clean --resume` rebuilds the runtime from it and
goes on from there. The workspace is reset to the commit it had then, so a package cut off half
way starts again from the beginning."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cleansweep.core.io import from_dict, to_dict
from cleansweep.core.models import CleanupItem, EditResult, RunResult

from .runtime import Package

FILE = "checkpoint.json"
STATE = (
    "brief",
    "baseline",
    "ui_base",
    "environment",
    "verdicts",
    "investigated",
    "current",
    "item_diffs",
    "checks",
    "audited",
    "planned",
    "plan_only",
    "untested",
    "approved",
    "reverting",
    "revert_all",
    "final",
    "delivery_tip",
    "stopped",
    "error",
    "turns",
    "llm_back_steps",
    "budget_warned",
    "resumed",
)
WORKSPACE = ("base", "test_runs", "python", "extra_env", "pytest_args", "test_command")


def _point(rt) -> tuple:
    return (rt.phases.phase, len(rt.phases.history), rt.current)


def save(rt) -> None:
    """Write the checkpoint if the run has reached a new safe point since the last one."""
    if rt.saved_at == _point(rt):
        return
    rt.saved_at = _point(rt)
    data = {
        "phase": rt.phases.phase,
        "history": rt.phases.history,
        "back_steps": rt.phases.back_steps,
        "seconds": round(time.time() - rt.phases.t0, 3),
        "head": rt.ws._git("rev-parse", "HEAD").strip(),
        "workspace": {k: getattr(rt.ws, k) for k in WORKSPACE},
        "items": to_dict(list(rt.items.values())),
        "results": to_dict(list(rt.results.values())),
        "packages": to_dict(rt.packages),
        "state": {k: to_dict(getattr(rt, k)) for k in STATE},
        "retry": sorted(rt.retry),
        "before_verdict": rt.before_verdict,
        "lessons": rt.lessons.lessons,
        "llm_calls": rt.run_budget.used_llm,
    }
    path = rt.out / FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    os.replace(tmp, path)  # a crash while writing leaves the previous checkpoint


def load(out: str | Path) -> dict | None:
    """A run folder's checkpoint, or None when it has none."""
    path = Path(out) / FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def restore(rt, data: dict) -> None:
    """Put a checkpoint's state back into a fresh runtime and reset its workspace."""
    rt.ws.rollback(data["head"])
    for key, value in data["workspace"].items():
        setattr(rt.ws, key, value)
    rt.items = {d["item_id"]: from_dict(CleanupItem, d) for d in data["items"]}
    rt.results = {d["item_id"]: from_dict(EditResult, d) for d in data["results"]}
    rt.packages = [from_dict(Package, d) for d in data["packages"]]
    for key in STATE:
        setattr(rt, key, data["state"][key])
    if rt.baseline and isinstance(rt.baseline.get("result"), dict):
        rt.baseline["result"] = from_dict(RunResult, rt.baseline["result"])
    rt.retry = set(data["retry"])
    rt.before_verdict = {k: tuple(v) for k, v in data["before_verdict"].items()}
    rt.lessons.lessons = data["lessons"]
    rt.run_budget.used_llm = data["llm_calls"]
    rt.run_budget.started = time.time() - data["seconds"]  # time asleep does not count
    phases = rt.phases
    phases.phase, phases.history = data["phase"], data["history"]
    phases.back_steps = data["back_steps"]
    phases.t0 = time.time() - data["seconds"]
    rt.log.phase = data["phase"]
    rt.resumed = [*rt.resumed, data["phase"]]
    rt.saved_at = _point(rt)
