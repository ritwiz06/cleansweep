from __future__ import annotations

import re
from pathlib import Path

from cleansweep.core.models import CleanupItem

PROMPT = (Path(__file__).parent / "prompts" / "repair.txt").read_text()
FENCE = re.compile(r"```(?:diff|patch)?\n(.*?)```", re.S)


def propose_fix(item: CleanupItem, failure_log: str, repo_dir: str, llm) -> str | None:
    """Ask the LLM for one repair diff after a failed edit; None if it has no fix."""
    if llm is None:
        return None
    prompt = (
        PROMPT.replace("{category}", item.category)
        .replace("{key}", item.unit.key)
        .replace("{reason}", item.reason)
        .replace("{diff}", item.patch or "(see failure)")
        .replace("{failure_log}", failure_log[-4000:])
    )
    reply = llm.chat([{"role": "user", "content": prompt}])
    if "NO_FIX" in reply:
        return None
    m = FENCE.search(reply)
    diff = m.group(1) if m else reply
    return diff if "--- " in diff and "+++ " in diff else None
