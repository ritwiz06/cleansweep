from __future__ import annotations

from cleansweep.core.models import STATS_KEYS, SweepReport


def summarize(report: SweepReport, hidden: dict | None = None) -> dict:
    """One flat row per run: method, counts from stats, and hidden-check results."""
    row = {
        "repo_id": report.repo_id,
        "method": report.method,
        "policy": report.policy,
        "seed": report.seed,
    }
    row.update({k: report.stats.get(k, 0) for k in STATS_KEYS})
    hidden = hidden or {}
    row["hidden_available"] = hidden.get("available", False)
    row["behavior_changed"] = hidden.get("behavior_changed")
    row["hidden_failed_after"] = len(hidden.get("hidden_after", {}).get("failed_ids", []))
    row["visible_new_failures"] = len(hidden.get("visible_new_failures", []))
    if "loc_before" in hidden:
        row["loc_delta"] = hidden["loc_before"] - hidden["loc_after"]
    return row
