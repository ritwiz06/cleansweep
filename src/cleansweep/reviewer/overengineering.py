from __future__ import annotations

import os
from pathlib import Path

from cleansweep.analysis import extract_features
from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.core.models import CleanupItem, CodeUnit

from .detectors import _settings, _unit_at, item_id

PROMPT = (Path(__file__).parent / "prompts" / "overengineering.txt").read_text()
ENV = "CLEANSWEEP_OVERENGINEERING"
EVIDENCE = "over-engineering review"
KINDS = {
    "extra_check": "extra check",
    "needless_abstraction": "needless abstraction",
    "unused_parameter": "unused parameter",
    "impossible_case": "defensive code for a case that can't happen",
}


def enabled(cfg: dict) -> bool:
    """CLEANSWEEP_OVERENGINEERING (0/1) wins over reviewer.overengineering."""
    raw = os.environ.get(ENV, "").strip().lower()
    if raw:
        return raw not in ("0", "false", "off", "no")
    return bool(cfg.get("overengineering", True))


def select_files(repo_dir: str, features, skip: set[str], max_files: int) -> list[str]:
    """Agent-written files if the features mark any; otherwise all non-test .py files."""
    candidates = [p for p in iter_py_files(repo_dir) if not is_test_file(p) and p not in skip]
    agent: set[str] = set()
    if features is not None and len(features) and "written_by_agent" in features:
        marked = features.index[features["written_by_agent"] == 1]
        agent = {key.split("::", 1)[0] for key in marked}
    if agent:
        candidates = [p for p in candidates if p in agent]
    return candidates[:max_files]


def pack(files: list[tuple[str, str]], budget: int) -> list[list[tuple[str, str]]]:
    """Group small files into requests under `budget` characters; cut files that are too big."""
    requests: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for path, text in files:
        if len(text) > budget:
            text = text[:budget] + "\n... (rest of the file not shown)"
        if current and size + len(text) > budget:
            requests.append(current)
            current, size = [], 0
        current.append((path, text))
        size += len(text)
    if current:
        requests.append(current)
    return requests


def _numbered(repo_dir: str, path: str) -> tuple[str, int]:
    lines = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(f"{n:>4} {line}" for n, line in enumerate(lines, 1)), len(lines)


def to_items(
    findings: list, graph, line_counts: dict[str, int], taken: set[str]
) -> list[CleanupItem]:
    """Turn the model's findings into report-only items, one per code unit."""
    items: dict[str, CleanupItem] = {}
    for f in findings:
        if not isinstance(f, dict) or str(f.get("path")) not in line_counts:
            continue
        path = str(f["path"])
        try:
            start = int(f["start_line"])
            end = int(f.get("end_line") or start)
        except (KeyError, TypeError, ValueError):
            continue
        reason = str(f.get("reason") or "").strip()
        if not reason or not 1 <= start <= end <= line_counts[path]:
            continue
        owner = _unit_at(graph, path, start)
        unit = CodeUnit(
            path, owner.kind if owner else "file", owner.name if owner else None, start, end
        )
        if unit.key in taken:
            continue
        kind = KINDS.get(str(f.get("kind")), "over-engineering")
        if unit.key in items:
            item = items[unit.key]
            item.reason = f"{item.reason} {reason}"
            item.evidence.append(f"{kind}: lines {start}-{end}")
            item.unit.start_line = min(item.unit.start_line, start)
            item.unit.end_line = max(item.unit.end_line, end)
            continue
        confidence = f.get("confidence")
        items[unit.key] = CleanupItem(
            item_id(unit.key, "other"),
            unit,
            "other",
            "report_only",
            "suggest",
            reason,
            [EVIDENCE, f"{kind}: lines {start}-{end}"],
            ["llm"],
            llm_confidence=float(confidence) if isinstance(confidence, int | float) else None,
        )
    return list(items.values())


def review_overengineering(
    items: list[CleanupItem], repo_dir: str, graph, llm, features=None
) -> list[CleanupItem]:
    """Ask the LLM for over-engineering; return new suggest-lane, report_only items."""
    cfg = _settings()
    if llm is None or not enabled(cfg):
        return []
    if features is None:
        features = extract_features(repo_dir, graph)
    leftovers = {i.unit.path for i in items if i.category == "leftover_file"}
    files = select_files(repo_dir, features, leftovers, cfg.get("overengineering_max_files", 20))
    texts, line_counts = [], {}
    for path in files:
        text, count = _numbered(repo_dir, path)
        if count:
            texts.append((path, text))
            line_counts[path] = count
    findings: list = []
    for request in pack(texts, cfg.get("overengineering_budget_chars", 12000)):
        body = "\n\n".join(f"### {path}\n{text}" for path, text in request)
        try:
            reply = llm.chat_json([{"role": "user", "content": PROMPT.replace("{files}", body)}])
        except ValueError:
            continue  # unreadable answer: skip this group of files
        findings += reply if isinstance(reply, list) else reply.get("findings", [])
    return to_items(findings, graph, line_counts, {i.unit.key for i in items})
