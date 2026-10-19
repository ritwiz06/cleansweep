from __future__ import annotations

from cleansweep.core.models import CleanupItem, CommitEvent


def make_batches(items: list[CleanupItem], max_size: int = 8) -> list[list[CleanupItem]]:
    return [[i] for i in items]


def apply_with_bisection(batches: list[list[CleanupItem]], check_fn) -> dict:
    accepted, rejected = [], []
    for batch in batches:
        (accepted if check_fn(batch) else rejected).extend(i.item_id for i in batch)
    return {"accepted": accepted, "rejected": rejected, "n_checks": len(batches)}


def should_sweep(policy: str, state: dict) -> bool:
    return True


def simulate(
    history: list[CommitEvent], repo_dir: str, policy: str, cfg: dict | None = None
) -> dict:
    return {
        "policy": policy,
        "sweeps": len(history),
        "slop_debt": 0.0,
        "final_slop": 0,
        "resurrection_rate": 0.0,
        "est_test_runs": len(history),
    }
