"""Method labels for the v3 experiments.

agentic                  the team (LLM-guided Manager, safe mode, the dynamic-reference resolver on)
agentic-no_resolver      the team with the resolver off (reviewer.dynamic_refs: off)
agentic-batch            the team with investigation batching (core.agents.investigate_batch: on)
agentic-no_research      the team without its research squad
agentic-single_agent     one agent that edits and checks its own edits
agentic-adaptive         only uncertain candidates go to an Investigator
agentic-thorough         the team in thorough mode
aider                    the external coding agent, with the fixed cleanup instruction
cleansweep               v1 (gatekeeper judge)
"""

from __future__ import annotations

import os
import signal
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

TEAM_VARIANTS = {
    "agentic": {},
    "agentic-no_resolver": {"reviewer": {"dynamic_refs": "off"}},
    "agentic-batch": {"agents": {"investigate_batch": "on"}},
    "agentic-no_research": {"agents": {"ablation": "no_research"}},
    "agentic-single_agent": {"agents": {"ablation": "single_agent"}},
    "agentic-adaptive": {"agents": {"investigate": "adaptive"}},
    "agentic-thorough": {"mode": "thorough"},
}
EXTERNAL = ["aider"]
V1 = ["cleansweep"]
LABELS = [*TEAM_VARIANTS, *EXTERNAL, *V1]


@dataclass
class Method:
    label: str
    kind: str  # agentic, external or v1
    agents: dict = field(default_factory=dict)  # core.agents overrides
    reviewer: dict = field(default_factory=dict)  # reviewer overrides
    mode: str = "safe"


def resolve(label: str) -> Method:
    """The run settings for a v3 method label."""
    if label in TEAM_VARIANTS:
        spec = TEAM_VARIANTS[label]
        return Method(
            label,
            "agentic",
            dict(spec.get("agents", {})),
            dict(spec.get("reviewer", {})),
            spec.get("mode", "safe"),
        )
    if label in EXTERNAL:
        return Method(label, "external")
    if label in V1:
        return Method(label, "v1")
    raise ValueError(f"unknown method {label!r}; use one of {', '.join(LABELS)}")


def apply(cfg: dict, method: Method) -> dict:
    """A copy of cfg with the method's core.agents and reviewer overrides."""
    core = cfg.get("core", {})
    agents = {**core.get("agents", {}), **method.agents}
    if method.mode != "safe":
        agents["mode"] = method.mode
    out = {**cfg, "core": {**core, "agents": agents}}
    if method.reviewer:
        out["reviewer"] = {**cfg.get("reviewer", {}), **method.reviewer}
    return out


V1_CAP_MINUTES = 150  # v1 has no time budget of its own; the team's is 120 minutes on REAL


class Capped(Exception):
    """A run stopped by its time cap before it finished."""


@contextmanager
def time_cap(minutes: float):
    """Raise Capped in the main thread once the cap has passed."""

    def stop(signum, frame):
        raise Capped(f"not finished within {minutes:g} minutes")

    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, minutes * 60)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def run_method(target: str, label: str, cfg: dict, out: Path):
    """Run one method on a target (a folder or an "aidev:owner/name@sha" container target);
    returns its SweepReport, whose stats hold the final diff. v1 runs under V1_CAP_MINUTES and
    raises Capped when it does not finish; the runners record that, never a score."""
    from cleansweep.workflow import run_sweep

    method = resolve(label)
    if method.kind == "external":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from exp_external import run_external

        return run_external(target, {**cfg, "agent_out": str(out)})
    if method.kind == "v1":
        os.environ["CLEANSWEEP_JUDGE_MODE"] = "gatekeeper"
        with time_cap(cfg.get("exp", {}).get("v1_cap_minutes", V1_CAP_MINUTES)):
            return run_sweep(target, cfg, "cleansweep")
    os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    return run_sweep(target, {**apply(cfg, method), "agent_out": str(out)}, "agentic")
