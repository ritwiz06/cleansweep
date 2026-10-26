from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path

from cleansweep.analysis import extract_features
from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.core.models import CleanupItem, CodeUnit

from .detectors import _settings, _unit_at, item_id

PROMPT = (Path(__file__).parent / "prompts" / "overengineering.txt").read_text()
ENV = "CLEANSWEEP_OVERENGINEERING"
EVIDENCE = "over-engineering review"
log = logging.getLogger(__name__)
MAX_TEST_CALLS = 3
IMPOSSIBLE = re.compile(
    r"unreachable|can(?:'|no)t happen"
    r"|never (?:happens?|triggers?|be reached|reached|runs?|executes?)",
    re.IGNORECASE,
)
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


def wanted() -> bool:
    """True if the review would run (config and env switch), so callers can skip its setup."""
    return enabled(_settings())


def load_coverage(coverage_json: str | None) -> dict[str, dict[int, list[str]]]:
    """Per file and line, the tests that ran it (from Workspace.coverage_json)."""
    if not coverage_json or not Path(coverage_json).exists():
        return {}
    data = json.loads(Path(coverage_json).read_text(encoding="utf-8"))
    return {
        name.replace("\\", "/"): {
            int(line): [c for c in contexts if c]
            for line, contexts in info.get("contexts", {}).items()
        }
        for name, info in data.get("files", {}).items()
    }


def says_impossible(finding: dict) -> bool:
    return finding.get("kind") == "impossible_case" or bool(
        IMPOSSIBLE.search(str(finding.get("reason", "")))
    )


def _guard_bodies(tree: ast.Module, start: int, end: int) -> list[set[int]]:
    """Body lines of each if / try / except / assert guard whose header is in start..end."""
    bodies = []
    for node in ast.walk(tree):
        if not start <= getattr(node, "lineno", 0) <= end:
            continue
        if isinstance(node, ast.If):
            stmts = node.body
        elif isinstance(node, ast.Try | ast.TryStar):
            stmts = [s for handler in node.handlers for s in handler.body]
        elif isinstance(node, ast.ExceptHandler):
            stmts = node.body
        elif isinstance(node, ast.Assert):
            stmts = []  # the failing path has no lines of its own, so coverage can't show it
        else:
            continue
        bodies.append({n for stmt in stmts for n in range(stmt.lineno, stmt.end_lineno + 1)})
    return bodies


def evidence_lines(source: str | None, start: int, end: int) -> set[int]:
    """Lines whose coverage shows that a flagged "can't happen" case does happen.

    A guard's condition runs on every call, so for if / try / except / assert guards only
    the guarded block counts. Single-line findings, and findings without a guard, use any line.
    """
    every = set(range(start, end + 1))
    if start == end or source is None:
        return every
    try:
        bodies = _guard_bodies(ast.parse(source), start, end)
    except SyntaxError:
        return every
    return set().union(*bodies) if bodies else every


def drop_tested(
    findings: list, coverage: dict[str, dict[int, list[str]]], repo_dir: str | None = None
) -> list:
    """Drop "can't happen" findings whose guarded code a test runs; log each decision."""
    if not coverage:
        return findings
    sources: dict[str, str | None] = {}
    kept = []
    for f in findings:
        if not (isinstance(f, dict) and says_impossible(f)):
            kept.append(f)
            continue
        try:
            start = int(f["start_line"])
            end = int(f.get("end_line") or start)
        except (KeyError, TypeError, ValueError):
            kept.append(f)
            continue
        path = str(f.get("path"))
        if path not in sources:
            file = Path(repo_dir) / path if repo_dir else None
            sources[path] = (
                file.read_text(encoding="utf-8", errors="replace")
                if file and file.is_file()
                else None
            )
        lines = coverage.get(path, {})
        hits: dict[str, int] = {}
        for n in evidence_lines(sources[path], start, end):
            for test in lines.get(n, []):
                hits[test] = hits.get(test, 0) + 1
        reason = str(f.get("reason", ""))[:120]
        if hits:
            ranked = sorted(hits, key=lambda t: (-hits[t], t))
            log.info(
                "dropped over-engineering finding %s:%d-%d (%s): %d test(s) run the guarded "
                "code, e.g. %s",
                path,
                start,
                end,
                reason,
                len(ranked),
                ", ".join(ranked[:3]),
            )
            continue
        if any(lines.get(n) for n in range(start, end + 1)):
            log.info(
                "kept over-engineering finding %s:%d-%d (%s): tests run the condition but not "
                "the guarded code",
                path,
                start,
                end,
                reason,
            )
        kept.append(f)
    return kept


def _test_lines(repo_dir: str) -> list[tuple[str, int, str]]:
    out = []
    for path in iter_py_files(repo_dir):
        if is_test_file(path):
            text = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace")
            out += [(path, n, line.strip()) for n, line in enumerate(text.splitlines(), 1)]
    return out


def _function_names(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names += [
                n.name for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
    return names


def calls_from_tests(source: str, test_lines: list[tuple[str, int, str]]) -> list[str]:
    """Up to MAX_TEST_CALLS test lines calling each function defined in `source`."""
    out = []
    for name in dict.fromkeys(_function_names(source)):
        call = re.compile(rf"(?<![\w]){re.escape(name)}\(")
        hits = [f"{p}:{n}: {line}" for p, n, line in test_lines if call.search(line)]
        out += [f"  {name}: {hit}" for hit in hits[:MAX_TEST_CALLS]]
    return out


def _numbered(repo_dir: str, path: str) -> tuple[str, int]:
    lines = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(f"{n:>4} {line}" for n, line in enumerate(lines, 1)), len(lines)


def to_items(
    findings: list, graph, line_counts: dict[str, int], existing: dict[str, CleanupItem]
) -> list[CleanupItem]:
    """Turn the model's findings into report-only items, one per code unit.

    A finding on a unit that already has a cleanup item is attached to that item as
    evidence instead (lane and action unchanged); only new items are returned.
    """
    items: dict[str, CleanupItem] = {}
    seen: set[tuple] = set()
    for f in findings:
        if not isinstance(f, dict) or str(f.get("path")) not in line_counts:
            continue
        signature = tuple(
            str(f.get(k)) for k in ("path", "start_line", "end_line", "kind", "reason")
        )
        if signature in seen:
            continue  # the same finding repeated (e.g. across requests)
        seen.add(signature)
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
        if unit.key in existing:
            target = existing[unit.key]
            target.evidence.append(f"{EVIDENCE}: {reason}")
            if "overengineering" not in target.sources:
                target.sources.append("overengineering")
            log.info(
                "attached over-engineering finding %s:%d-%d to the existing item for %s",
                path,
                start,
                end,
                unit.key,
            )
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
    items: list[CleanupItem], repo_dir: str, graph, llm, features=None, coverage_json=None
) -> list[CleanupItem]:
    """Ask the LLM for over-engineering; return new suggest-lane, report_only items.

    With coverage, "can't happen" findings on lines that a test runs are dropped.
    """
    cfg = _settings()
    if llm is None or not enabled(cfg):
        return []
    if features is None:
        features = extract_features(repo_dir, graph)
    leftovers = {i.unit.path for i in items if i.category == "leftover_file"}
    files = select_files(repo_dir, features, leftovers, cfg.get("overengineering_max_files", 20))
    texts, line_counts = [], {}
    tests = _test_lines(repo_dir)
    for path in files:
        text, count = _numbered(repo_dir, path)
        if count:
            source = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace")
            calls = calls_from_tests(source, tests)
            if calls:
                text += "\nTest calls:\n" + "\n".join(calls)
            texts.append((path, text))
            line_counts[path] = count
    findings: list = []
    for request in pack(texts, cfg.get("overengineering_budget_chars", 12000)):
        body = "\n\n".join(f"### {path}\n{text}" for path, text in request)
        try:
            reply = llm.chat_json([{"role": "user", "content": PROMPT.replace("{files}", body)}])
        except (
            Exception
        ) as exc:  # optional, report-only step: a failed request must not stop the sweep
            log.warning(
                "over-engineering review skipped %d file(s): %s: %s",
                len(request),
                type(exc).__name__,
                str(exc).splitlines()[0][:200],
            )
            continue
        findings += reply if isinstance(reply, list) else reply.get("findings", [])
    findings = drop_tested(findings, load_coverage(coverage_json), repo_dir)
    return to_items(findings, graph, line_counts, {i.unit.key: i for i in items})
