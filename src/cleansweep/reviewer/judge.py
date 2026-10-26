from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

from cleansweep.core.models import CleanupItem

PROMPT = (Path(__file__).parent / "prompts" / "judge.txt").read_text()
MODES = ("gatekeeper", "advisory", "off")
MODE_ENV = "CLEANSWEEP_JUDGE_MODE"
DECISIONS = ("remove", "suggest", "keep")
STILL_USED = "Judge thinks this is still used:"
FORMAT_REASON = "Formatting only; the Guard checks the code structure is unchanged."
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


def _has_main_block(repo_dir: str, path: str) -> bool | None:
    try:
        tree = ast.parse((Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    return any(
        isinstance(node, ast.If)
        and "__name__" in (test := ast.unparse(node.test))
        and "__main__" in test
        for node in tree.body
    )


def _leftover_signals(item: CleanupItem, graph, repo_dir: str | None, text: str) -> dict:
    # A leftover script's own __main__ block makes it an "entry point", so reachability says
    # nothing useful here; who imports it and whether config mentions it does.
    from cleansweep.analysis.graph import name_in_configs

    out: dict = {}
    importers = getattr(graph, "imported_by", None)
    if importers is not None:
        out["imported_by"] = len(importers.get(item.unit.path, ()))
    elif "no other file imports it" in text:
        out["imported_by"] = 0
    if repo_dir:
        if (main := _has_main_block(repo_dir, item.unit.path)) is not None:
            out["has_main_block"] = main
        out["mentioned_in_config"] = name_in_configs(repo_dir, item.unit.path)
    elif "not mentioned in project config files" in text:
        out["mentioned_in_config"] = False
    return out


def scratch_context(items: list[CleanupItem], repo_dir: str | None, graph) -> dict | None:
    """What separates project code from the agent's leftovers, for signals on files the agent
    created; None when the repo has no agent patch commit."""
    from cleansweep.analysis.scope import agent_scope

    scope = agent_scope(repo_dir) if repo_dir else None
    if scope is None:
        return None
    scratch = {f for f in scope.files_added if scope.outside_project(f)}
    leftovers = {i.unit.path for i in items if i.category == "leftover_file"}
    non_project = scratch | leftovers
    strings: set[str] = set()
    if graph is not None and any(p in scope.files_added for p in leftovers):
        for path, mod in getattr(graph, "modules", {}).items():
            if path not in non_project and mod.tree is not None:
                strings.update(
                    n.value
                    for n in ast.walk(mod.tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                )
    return {
        "created": set(scope.files_added),
        # files that existed before the patch and weren't touched can't need a new file
        "can_import": scope.files - non_project,
        "project_strings": strings,
    }


def _agent_file_signals(item: CleanupItem, graph, repo_dir: str, ctx: dict) -> dict:
    # Only project code counts: other leftover or scratch files that import this one, or a
    # bare file name like "admin" that appears in a config or a string, say nothing.
    from cleansweep.analysis.graph import import_name, module_in_configs

    path = item.unit.path
    importers = set(getattr(graph, "imported_by", {}).get(path, ())) & ctx["can_import"]
    out: dict = {"created_by_agent_patch": True, "imported_by": len(importers)}
    if (main := _has_main_block(repo_dir, path)) is not None:
        out["has_main_block"] = main
    out["mentioned_in_config"] = module_in_configs(repo_dir, path)
    out["dynamic_risk"] = import_name(path) in ctx["project_strings"]
    return out


def signals(
    item: CleanupItem, graph=None, repo_dir: str | None = None, context: dict | None = None
) -> dict:
    """The detector facts behind an item, as named fields the judge can weigh.

    context (from scratch_context) gives files the agent created signals that count only
    project code."""
    text = " | ".join(item.evidence)
    out: dict = {}
    if m := VULTURE.search(text):
        out["vulture_confidence"] = int(m.group(1))
    in_graph = graph is not None and item.unit.kind in GRAPH_KINDS
    if item.category == "leftover_file" and context and item.unit.path in context["created"]:
        out.update(_agent_file_signals(item, graph, repo_dir, context))
        return out
    if item.category == "leftover_file":
        out.update(_leftover_signals(item, graph, repo_dir, text))
    elif in_graph:
        out["reachable_from_entry_points"] = graph.is_reachable(item.unit.key)
    if in_graph:
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


def resolve_mode(mode: str | None, cfg: dict) -> str:
    """Pick the judge mode: explicit argument, then CLEANSWEEP_JUDGE_MODE, then the config."""
    mode = mode or os.environ.get(MODE_ENV, "").strip().lower() or cfg.get("judge_mode")
    mode = mode or "gatekeeper"
    if mode not in MODES:
        raise ValueError(
            f"judge mode must be one of {MODES} (from {MODE_ENV} or "
            f"reviewer.judge_mode), got {mode!r}"
        )
    return mode


def _apply(item: CleanupItem, row: dict, mode: str) -> None:
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
    if mode == "gatekeeper":
        if decision == "keep":
            item.lane, item.action = "suggest", "report_only"
        elif decision == "suggest":
            item.lane = "suggest"
    if item.category == "security":
        item.lane, item.action = "suggest", "report_only"


def judge_items(
    items: list[CleanupItem],
    repo_dir: str,
    llm,
    batch_size: int | None = None,
    mode: str | None = None,
    graph=None,
) -> list[CleanupItem]:
    """Ask the LLM about each item. Every item stays in the plan; the mode decides lanes.

    gatekeeper: "suggest" and "keep" move an item to the suggest lane.
    advisory: only the reason and confidence are recorded; the Guard decides.
    off: the judge is skipped.
    """
    if llm is None:
        return items
    from .detectors import _settings

    cfg = _settings()
    mode = resolve_mode(mode, cfg)
    if mode == "off":
        return items
    batch_size = batch_size or cfg.get("judge_batch_size", 10)
    context = cfg.get("snippet_context_lines", 10)

    # formatting can't change behavior, and the Guard compares the AST anyway
    for item in items:
        if item.category == "format":
            item.reason = FORMAT_REASON
    to_judge = [it for it in items if it.category != "format"]

    scratch = scratch_context(items, repo_dir, graph)
    decisions: dict[str, dict] = {}
    for request in group_requests(to_judge, batch_size):
        payload = [
            {
                "item_id": it.item_id,
                "category": it.category,
                "unit": it.unit.key,
                "signals": signals(it, graph, repo_dir, scratch),
                "evidence": it.evidence,
                "code": snippet(repo_dir, it, context),
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
    for item in to_judge:
        if item.item_id in decisions:
            _apply(item, decisions[item.item_id], mode)
    return items
