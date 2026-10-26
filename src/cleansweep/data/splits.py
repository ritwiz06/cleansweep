"""Experiment tiers over the PatchDiff patches (data/splits/swebench_tier*.json)."""

from __future__ import annotations

import json
import shlex
from collections import defaultdict
from pathlib import Path

from cleansweep.core.models import AgentPatch

START = ">>>>> Start Test Output"


def eval_test_command(eval_script: str) -> str:
    """The test command line of a SWE-bench eval script (the line after the start marker)."""
    lines = eval_script.splitlines()
    for i, line in enumerate(lines):
        if START in line and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def has_directives(command: str) -> bool:
    """True if the command names test files or modules (else it runs a whole test suite)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    args = [t for t in tokens if "=" not in t][1:]  # skip env assignments and the program
    return any(not t.startswith("-") and "test" in t for t in args)


def candidates(
    patches: list[AgentPatch], rows: dict[str, dict], n_agents: int = 3
) -> dict[str, list[AgentPatch]]:
    """Instances where every agent's patch is plausible and labeled, and tests are targeted."""
    by_instance: dict[str, list[AgentPatch]] = defaultdict(list)
    for p in patches:
        by_instance[p.instance_id].append(p)
    out = {}
    for instance_id, group in by_instance.items():
        row = rows.get(instance_id)
        if row is None or len(group) < n_agents:
            continue
        if any(p.differs_from_oracle is None for p in group):
            continue
        if not has_directives(eval_test_command(row["eval_script"])):
            continue
        out[instance_id] = sorted(group, key=lambda p: p.agent)
    return out


def _round_robin(groups: dict[str, list[AgentPatch]], rows: dict, prefer: list[str]) -> list[str]:
    by_repo: dict[str, list[str]] = defaultdict(list)
    for instance_id in sorted(groups):
        by_repo[rows[instance_id]["repo"]].append(instance_id)
    repos = [r for r in prefer if r in by_repo] + sorted(r for r in by_repo if r not in prefer)
    order = []
    while any(by_repo[r] for r in repos):
        for repo in repos:
            if by_repo[repo]:
                order.append(by_repo[repo].pop(0))
    return order


def pick(
    groups: dict[str, list[AgentPatch]],
    rows: dict,
    size: int,
    share: float,
    prefer: list[str],
    start: list[AgentPatch] | None = None,
) -> list[AgentPatch]:
    """Whole instances (fewer Docker images) in repo round-robin order, until `size` patches,
    with about `share` of them differing from the oracle. `start` patches are kept first."""
    chosen = list(start or [])
    used = {p.instance_id for p in chosen}
    want_true = round(share * size)
    n_true = sum(bool(p.differs_from_oracle) for p in chosen)
    for instance_id in _round_robin(groups, rows, prefer):
        room = size - len(chosen)
        if room <= 0:
            break
        if instance_id in used:
            continue
        group = groups[instance_id][:room]
        k = sum(bool(p.differs_from_oracle) for p in group)
        if n_true + k > want_true:
            continue
        # leave room for the differing patches still needed
        if room - len(group) < want_true - n_true - k:
            continue
        chosen += group
        used.add(instance_id)
        n_true += k
    return chosen


def tasks_tier(
    groups: dict[str, list[AgentPatch]],
    rows: dict,
    n_tasks: int,
    prefer: list[str],
    start: list[AgentPatch],
) -> list[AgentPatch]:
    """Up to n_tasks instances with all their patches, starting from the smaller tier."""
    chosen = list(start)
    used = {p.instance_id for p in chosen}
    for instance_id in _round_robin(groups, rows, prefer):
        if len(used) >= n_tasks:
            break
        if instance_id not in used:
            chosen += groups[instance_id]
            used.add(instance_id)
    return chosen


def entry(p: AgentPatch, rows: dict) -> dict:
    return {
        "instance_id": p.instance_id,
        "agent": p.agent,
        "repo": rows[p.instance_id]["repo"],
        "differs_from_oracle": p.differs_from_oracle,
    }


def write_tier(path: str | Path, patches: list[AgentPatch], rows: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps([entry(p, rows) for p in patches], indent=1) + "\n")


def load_tier(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())
