from __future__ import annotations

from cleansweep.core.models import CommitEvent


def simulate(
    history: list[CommitEvent], repo_dir: str, policy: str, cfg: dict | None = None
) -> dict:
    """Replay a repo history under a sweep policy (EA-06; not built yet)."""
    raise NotImplementedError("history replay is task EA-06")
