from __future__ import annotations

from datetime import datetime


def _day(ts) -> str:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts.date().isoformat() if ts else ""


def should_sweep(policy: str, state: dict) -> bool:
    """Decide whether to sweep now, given commits/PRs since the last sweep and slop size."""
    if policy == "now":
        return True
    if policy == "every_pr":
        return state.get("prs_since_sweep", state.get("commits_since_sweep", 0)) >= 1
    if policy == "every_n":
        n = state.get("n", 5)
        return state.get("prs_since_sweep", state.get("commits_since_sweep", 0)) >= n
    if policy == "daily":
        last = state.get("last_sweep_time")
        return last is None or _day(state.get("now")) != _day(last)
    if policy == "adaptive":
        loc = max(state.get("repo_loc", 0), 1)
        return state.get("slop_loc", 0) / loc >= state.get("threshold", 0.02)
    raise ValueError(f"unknown policy: {policy}")
