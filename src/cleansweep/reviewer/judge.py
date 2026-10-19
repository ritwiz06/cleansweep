from __future__ import annotations

import json
from pathlib import Path

from cleansweep.core.models import CleanupItem

PROMPT = (Path(__file__).parent / "prompts" / "judge.txt").read_text()
LANE_FOR = {"remove": "safe", "suggest": "suggest"}


def snippet(repo_dir: str, item: CleanupItem, context: int = 10) -> str:
    path = Path(repo_dir) / item.unit.path
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max((item.unit.start_line or 1) - context, 1)
    end = min((item.unit.end_line or item.unit.start_line or 40) + context, len(lines))
    return "\n".join(f"{i:>4} {lines[i - 1]}" for i in range(start, end + 1))


def judge_items(
    items: list[CleanupItem], repo_dir: str, llm, batch_size: int = 10
) -> list[CleanupItem]:
    """Ask the LLM to confirm, demote or drop each item; return the items that stay."""
    if llm is None:
        return items
    decisions: dict[str, dict] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        payload = [
            {
                "item_id": it.item_id,
                "category": it.category,
                "unit": it.unit.key,
                "evidence": it.evidence,
                "code": snippet(repo_dir, it),
            }
            for it in batch
        ]
        prompt = PROMPT.replace("{items}", json.dumps(payload, indent=1))
        reply = llm.chat_json([{"role": "user", "content": prompt}])
        for row in reply if isinstance(reply, list) else reply.get("items", []):
            if isinstance(row, dict) and "item_id" in row:
                decisions[row["item_id"]] = row
    kept = []
    for item in items:
        d = decisions.get(item.item_id)
        if d is None:
            kept.append(item)
            continue
        decision = str(d.get("decision", "")).lower()
        if decision == "keep":
            continue
        if decision in LANE_FOR and item.lane == "safe":
            item.lane = LANE_FOR[decision]
        if d.get("reason"):
            item.reason = str(d["reason"])
        if d.get("confidence") is not None:
            item.llm_confidence = float(d["confidence"])
        item.sources.append("llm")
        kept.append(item)
    return kept
