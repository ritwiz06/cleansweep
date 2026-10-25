from __future__ import annotations

import json
import re
from pathlib import Path

from cleansweep.core.models import CleanupItem

PROMPT = (Path(__file__).parent / "prompts" / "judge.txt").read_text()
DECISIONS = ("remove", "suggest", "keep")
STILL_USED = "Judge thinks this is still used:"
VULTURE = re.compile(r"vulture: unused \w+ \((\d+)% confidence\)")
DEPTRY = re.compile(r"deptry (DEP\d+)")
SIMILARITY = re.compile(r"similarity ([\d.]+)")
IDENTICAL = re.compile(r"(?<!near-)identical body")
GRAPH_KINDS = ("file", "function", "class")


def snippet(repo_dir: str, item: CleanupItem, context: int = 10) -> str:
    path = Path(repo_dir) / item.unit.path
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max((item.unit.start_line or 1) - context, 1)
    end = min((item.unit.end_line or item.unit.start_line or 40) + context, len(lines))
    return "\n".join(f"{i:>4} {lines[i - 1]}" for i in range(start, end + 1))


def signals(item: CleanupItem, graph=None) -> dict:
    """The detector facts behind an item, as named fields the judge can weigh."""
    text = " | ".join(item.evidence)
    out: dict = {}
    if m := VULTURE.search(text):
        out["vulture_confidence"] = int(m.group(1))
    if graph is not None and item.unit.kind in GRAPH_KINDS:
        out["reachable_from_entry_points"] = graph.is_reachable(item.unit.key)
        out["dynamic_risk"] = graph.dynamic_risk(item.unit.key)
    elif "dynamic" in text:
        out["dynamic_risk"] = True
    if m := DEPTRY.search(text):
        out["deptry_code"] = m.group(1)
        out["imported_anywhere_in_repo"] = m.group(1) != "DEP002"
        if "not mentioned in any config" in text:
            out["mentioned_in_config_or_ci"] = False
        elif " is mentioned in " in text:
            out["mentioned_in_config_or_ci"] = True
    if item.keep_target:
        out["duplicate_of"] = item.keep_target
        out["identical_body"] = bool(IDENTICAL.search(text))
        if m := SIMILARITY.search(text):
            out["duplicate_similarity"] = float(m.group(1))
    return out


def group_requests(items: list[CleanupItem], batch_size: int) -> list[list[CleanupItem]]:
    """Pack items into requests so a file's items, and duplicate pairs, are judged together."""
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k

    def link(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for item in items:
        link(item.item_id, f"file:{item.unit.path}")
        if item.keep_target:
            link(item.item_id, f"file:{item.keep_target.split('::', 1)[0]}")
    groups: dict[str, list[CleanupItem]] = {}
    for item in items:
        groups.setdefault(find(item.item_id), []).append(item)

    requests: list[list[CleanupItem]] = []
    current: list[CleanupItem] = []
    for group in groups.values():
        # a group bigger than batch_size is still sent whole: consistency beats size
        if current and len(current) + len(group) > batch_size:
            requests.append(current)
            current = []
        current += group
    if current:
        requests.append(current)
    return requests


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
    items: list[CleanupItem],
    repo_dir: str,
    llm,
    batch_size: int = 10,
    graph=None,
) -> list[CleanupItem]:
    """Ask the LLM about each item. Every item stays in the plan; "keep" moves it to suggest."""
    if llm is None:
        return items

    decisions: dict[str, dict] = {}
    for request in group_requests(items, batch_size):
        payload = [
            {
                "item_id": it.item_id,
                "category": it.category,
                "unit": it.unit.key,
                "signals": signals(it, graph),
                "evidence": it.evidence,
                "code": snippet(repo_dir, it),
            }
            for it in request
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
