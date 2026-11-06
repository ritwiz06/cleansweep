"""Method labels for the v3 experiments.

agentic                  the team (LLM-guided Manager, safe mode, the dynamic-reference resolver on)
agentic-no_resolver      the team with the resolver off (reviewer.dynamic_refs: off)
agentic-batch            the team with investigation batching (core.agents.investigate_batch: on)
agentic-no_research      the team without its research squad
agentic-single_agent     one agent that edits and checks its own edits
agentic-adaptive         only uncertain candidates go to an Investigator
agentic-thorough         the team in thorough mode
agentic-m2               the team with the second model family as the agents' model (SECOND_MODEL)
agentic-single_agent-m2  the single agent with the second model
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
    "agentic-m2": {"model": "second"},
    "agentic-single_agent-m2": {"agents": {"ablation": "single_agent"}, "model": "second"},
}
# the second model family (docs/preregistration_v3.md); the auditor's model differs from both
SECOND_MODEL = "deepseek-v4-1-flash"
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
    model: str = ""  # the agents' model when not VOYAGER_MODEL


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
            SECOND_MODEL if spec.get("model") == "second" else "",
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
    if method.model:  # read by the LLM client from this variable (as `clean --model` does)
        os.environ["CLEANSWEEP_MODEL"] = method.model
        out["core"]["llm"] = {**core.get("llm", {}), "model_env": "CLEANSWEEP_MODEL"}
    if method.reviewer:
        out["reviewer"] = {**cfg.get("reviewer", {}), **method.reviewer}
    return out


# One wall-clock cap and one LLM budget for every method (docs/preregistration_v3.md): the team
# and Aider stop on their own at them; v1 cannot and is cut at the cap; any run still going
# HARD_STOP_MINUTES after the cap is stopped. A run that reaches either is "timed out".
CAP_MINUTES = 120
LLM_BUDGET = 400
HARD_STOP_MINUTES = 5


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


def limits(cfg: dict) -> dict:
    """A copy of cfg with the cap and the budget set for every kind of method."""
    core = cfg.get("core", {})
    agents = core.get("agents", {})
    budget = {**agents.get("budget", {}), "minutes": CAP_MINUTES, "llm_calls": LLM_BUDGET}
    exp = {**cfg.get("exp", {}), "external_cap_min": CAP_MINUTES}
    exp["external_llm_budget"] = LLM_BUDGET
    llm = {**core.get("llm", {}), "max_calls": LLM_BUDGET}
    return {**cfg, "exp": exp, "core": {**core, "llm": llm, "agents": {**agents, "budget": budget}}}


def timed_out(stats: dict, minutes: float) -> str:
    """Why a finished run counts as timed out ("time cap", "LLM budget"), or ""."""
    if minutes >= CAP_MINUTES:
        return "time cap"
    stopped = stats.get("external", {}).get("stopped") or stats.get("agentic", {}).get("stopped")
    if (stats.get("llm_calls") or 0) >= LLM_BUDGET or stopped == "LLM budget":
        return "LLM budget"
    return ""


def run_method(target: str, label: str, cfg: dict, out: Path):
    """Run one method on a target (a folder or an "aidev:owner/name@sha" container target);
    returns its SweepReport, whose stats hold the final diff. Every method gets the same cap and
    budget (limits); a run cut at the cap raises Capped, which the runners record as timed out,
    never as a score."""
    from cleansweep.workflow import run_sweep

    method = resolve(label)
    cfg = limits(cfg)
    if method.kind == "external":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from exp_external import run_external

        with time_cap(CAP_MINUTES + HARD_STOP_MINUTES):
            return run_external(target, {**cfg, "agent_out": str(out)})
    if method.kind == "v1":
        os.environ["CLEANSWEEP_JUDGE_MODE"] = "gatekeeper"
        with time_cap(CAP_MINUTES):
            return run_sweep(target, cfg, "cleansweep")
    os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    with time_cap(CAP_MINUTES + HARD_STOP_MINUTES):
        return run_sweep(target, {**apply(cfg, method), "agent_out": str(out)}, "agentic")
