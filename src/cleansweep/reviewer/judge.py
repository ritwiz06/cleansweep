from __future__ import annotations

import json
from pathlib import Path

from cleansweep.core.models import CleanupItem

PROMPT = (Path(__file__).parent / "prompts" / "judge.txt").read_text()
DECISIONS = ("remove", "suggest", "keep")
STILL_USED = "Judge thinks this is still used:"


def snippet(repo_dir: str, item: CleanupItem, context: int = 10) -> str:
    path = Path(repo_dir) / item.unit.path
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max((item.unit.start_line or 1) - context, 1)
    end = min((item.unit.end_line or item.unit.start_line or 40) + context, len(lines))
    return "\n".join(f"{i:>4} {lines[i - 1]}" for i in range(start, end + 1))


def _apply(item: CleanupItem, row: dict) -> None:
    decision = str(row.get("decision", "")).lower()
    if decision not in DECISIONS:
        return
    reason = str(row.get("reason") or "").strip()
    if decision == "keep":
        reason = f"{STILL_USED} {reason}" if reason else STILL_USED.rstrip(":") + "."
    if reason:
        item.reason = reason
    confidence = row.get("confidence")
    if confidence is not None:
        item.llm_confidence = float(confidence)
    item.evidence.append(f"llm judge: {decision} (confidence {confidence})")
    if "llm" not in item.sources:
        item.sources.append("llm")
    if decision == "keep":
        item.lane, item.action = "suggest", "report_only"
    elif decision == "suggest":
        item.lane = "suggest"


def judge_items(
    items: list[CleanupItem], repo_dir: str, llm, batch_size: int = 10
) -> list[CleanupItem]:
    """Ask the LLM about each item. Every item stays in the plan; "keep" moves it to suggest."""
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
        try:
            reply = llm.chat_json([{"role": "user", "content": prompt}])
        except ValueError:
            continue  # unreadable answer: these items keep their detector lanes
        for row in reply if isinstance(reply, list) else reply.get("items", []):
            if isinstance(row, dict) and "item_id" in row:
                decisions[row["item_id"]] = row
    for item in items:
        if item.item_id in decisions:
            _apply(item, decisions[item.item_id])
    return items
