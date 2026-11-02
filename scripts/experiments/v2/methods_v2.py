"""Method labels for the v2 experiments: the agent team, its ablations, and v1's methods.

agentic                      the team (LLM-guided Manager)
agentic-<ablation>           no_research, broadcast, inline_artifacts, no_lessons,
                             no_coverage, single_agent
agentic-rules                the rule-based Manager
cleansweep-gatekeeper, cleansweep-advisory, guard_tests_only, tools_only, one_shot_llm
                             v1's methods, as scripts/experiments/v1/exp_swebench.py runs them
"""

from __future__ import annotations

ABLATIONS = [
    "no_research",
    "broadcast",
    "inline_artifacts",
    "no_lessons",
    "no_coverage",
    "single_agent",
]
V1 = {
    "cleansweep-gatekeeper": ("cleansweep", "gatekeeper"),
    "cleansweep-advisory": ("cleansweep", "advisory"),
    "guard_tests_only": ("guard_tests_only", "advisory"),
    "tools_only": ("tools_only", None),
    "one_shot_llm": ("one_shot_llm", None),
}
LABELS = ["agentic", *(f"agentic-{a}" for a in ABLATIONS), "agentic-rules", *V1]


def resolve(label: str) -> tuple[str, str | None, dict]:
    """(run_sweep method, v1 judge mode, core.agents overrides) for a method label."""
    if label in V1:
        method, judge = V1[label]
        return method, judge, {}
    if label == "agentic":
        return "agentic", None, {}
    if label == "agentic-rules":
        return "agentic", None, {"manager": "rules"}
    ablation = label.removeprefix("agentic-")
    if ablation not in ABLATIONS:
        raise ValueError(f"unknown method {label!r}; use one of {', '.join(LABELS)}")
    return "agentic", None, {"ablation": ablation}
