from __future__ import annotations

from collections.abc import Callable

from cleansweep.core.models import CleanupItem

TIER0 = {"format", "unused_import"}
TIER1 = {"leftover_file", "unused_dependency"}


def risk_tier(item: CleanupItem) -> int:
    if item.category in TIER0:
        return 0
    if item.category in TIER1:
        return 1
    if item.category == "dead_code" and (item.safe_score or 0) >= 0.6:
        return 1
    return 2


def _dynamic(item: CleanupItem) -> bool:
    return any("dynamic" in e for e in item.evidence)


def make_batches(items: list[CleanupItem], max_size: int = 8) -> list[list[CleanupItem]]:
    """Group items into batches by risk tier, low-risk first; dynamic-use items go alone."""
    batches: list[list[CleanupItem]] = []
    for tier in (0, 1, 2):
        group = [i for i in items if risk_tier(i) == tier and not _dynamic(i)]
        alone = [i for i in items if risk_tier(i) == tier and _dynamic(i)]
        batches += [group[k : k + max_size] for k in range(0, len(group), max(max_size, 1))]
        batches += [[i] for i in alone]
    return batches


def apply_with_bisection(
    batches: list[list[CleanupItem]], check_fn: Callable[[list[CleanupItem]], bool]
) -> dict:
    """Check each batch; split failing batches in half until the bad edits are isolated."""
    accepted: list[str] = []
    rejected: list[str] = []
    n_checks = 0

    def run(batch: list[CleanupItem]) -> None:
        nonlocal n_checks
        if not batch:
            return
        n_checks += 1
        if check_fn(batch):
            accepted.extend(i.item_id for i in batch)
        elif len(batch) == 1:
            rejected.append(batch[0].item_id)
        else:
            mid = len(batch) // 2
            run(batch[:mid])
            run(batch[mid:])

    for batch in batches:
        run(batch)
    return {"accepted": accepted, "rejected": rejected, "n_checks": n_checks}
