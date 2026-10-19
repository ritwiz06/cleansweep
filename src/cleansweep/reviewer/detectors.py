from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from cleansweep.analysis import build_graph, find_duplicates
from cleansweep.core.config import load_config
from cleansweep.core.models import CleanupItem, CodeUnit

DEFAULTS = {
    "leftover_patterns": [
        "reproduce*",
        "debug*",
        "scratch*",
        "tmp*",
        "*_old.py",
        "*_v[0-9].py",
        "*backup*",
        "*.bak",
        "*.orig",
    ],
    "vulture_min_confidence": 60,
    "duplicate_threshold": 0.8,
    "security_min_severity": "MEDIUM",
}
SEVERITY = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
# when two detectors flag the same unit, the first category in this list wins
CATEGORY_PRIORITY = [
    "security",
    "leftover_file",
    "duplicate",
    "wrapper",
    "dead_code",
    "unused_import",
    "unused_dependency",
    "format",
    "other",
]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}


def item_id(key: str, category: str) -> str:
    return hashlib.sha1(f"{key}{category}".encode()).hexdigest()[:10]


def make_item(
    unit: CodeUnit,
    category: str,
    action: str,
    lane: str,
    reason: str,
    evidence: list[str],
    sources: list[str],
    **extra,
) -> CleanupItem:
    return CleanupItem(
        item_id(unit.key, category),
        unit,
        category,
        action,
        lane,
        reason,
        evidence,
        sources,
        **extra,
    )


def _settings() -> dict:
    try:
        return {**DEFAULTS, **(load_config().get("reviewer") or {})}
    except Exception:
        return dict(DEFAULTS)


def _tool(args: list[str], cwd: str) -> tuple[int, str] | None:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", *args], cwd=cwd, capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "No module named" in proc.stderr:
        return None
    return proc.returncode, proc.stdout


def _is_test(path: str) -> bool:
    from cleansweep.analysis.graph import is_test_file

    return is_test_file(path)


def _unit_at(graph, path: str, line: int, name: str | None = None) -> CodeUnit | None:
    """Innermost function/class unit in `path` covering `line` (optionally matching a name)."""
    best = None
    for u in graph.units():
        if u.path != path or u.kind == "file" or not u.start_line or not u.end_line:
            continue
        if name and u.name.split(".")[-1] != name:
            continue
        if u.start_line <= line <= u.end_line and (
            best is None or u.end_line - u.start_line < best.end_line - best.start_line
        ):
            best = u
    return best


def detect_leftovers(repo_dir: str, graph, patterns: list[str]) -> list[CleanupItem]:
    from cleansweep.analysis.graph import name_in_configs

    root = Path(repo_dir)
    items = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        path = rel.as_posix()
        hits = [pat for pat in patterns if fnmatch.fnmatch(p.name, pat)]
        if not hits or _is_test(path):
            continue
        importers = sorted(getattr(graph, "imported_by", {}).get(path, ()))
        if importers or name_in_configs(repo_dir, path):
            continue
        items.append(
            make_item(
                CodeUnit(path, "file"),
                "leftover_file",
                "delete_file",
                "safe",
                f"{path} looks like a leftover file (scratch, debug or old copy) "
                "and nothing imports it.",
                [
                    f"file name matches {hits[0]!r}",
                    "no other file imports it",
                    "not mentioned in project config files",
                ],
                ["patterns", "graph"],
            )
        )
    return items


VULTURE_LINE = re.compile(
    r"^(.+?):(\d+): unused (function|method|class) '([^']+)' \((\d+)% confidence"
)


def detect_dead_code(repo_dir: str, graph, min_conf: int) -> list[CleanupItem]:
    out = _tool(["vulture", ".", "--min-confidence", str(min_conf)], repo_dir)
    if out is None:
        return []
    items = []
    for line in out[1].splitlines():
        m = VULTURE_LINE.match(line.strip())
        if not m:
            continue
        path, lineno, kind, name, conf = m.groups()
        path = path.removeprefix("./")
        if _is_test(path):
            continue
        unit = _unit_at(graph, path, int(lineno), name)
        if unit is None:
            unit = CodeUnit(path, "class" if kind == "class" else "function", name, int(lineno))
        if graph.is_reachable(unit.key):
            continue
        evidence = [
            f"vulture: unused {kind} ({conf}% confidence)",
            "not reachable from tests, __main__ or scripts in the call graph",
        ]
        lane = "safe"
        if graph.dynamic_risk(unit.key):
            lane = "suggest"
            evidence.append("may be used dynamically (getattr, string lookup or decorator)")
        items.append(
            make_item(
                unit,
                "dead_code",
                "delete_unit",
                lane,
                f"{unit.name} is never called anywhere in the project.",
                evidence,
                ["vulture", "graph"],
            )
        )
    return items


def detect_unused_imports(repo_dir: str) -> list[CleanupItem]:
    out = _tool(
        [
            "ruff",
            "check",
            "--isolated",
            "--select",
            "F401",
            "--output-format",
            "json",
            "--exit-zero",
            ".",
        ],
        repo_dir,
    )
    if out is None or not out[1].strip():
        return []
    items = []
    root = Path(repo_dir).resolve()
    for r in json.loads(out[1]):
        path = Path(r["filename"]).resolve().relative_to(root).as_posix()
        if path.endswith("__init__.py"):
            continue  # imports there are usually re-exports
        m = re.search(r"`([^`]+)`", r["message"])
        if not m:
            continue
        name = m.group(1)
        row = r["location"]["row"]
        unit = CodeUnit(path, "import", name, row, r["end_location"]["row"])
        items.append(
            make_item(
                unit,
                "unused_import",
                "remove_import",
                "safe",
                f"The import of {name} in {path} is never used.",
                [f"ruff F401 at line {row}"],
                ["ruff"],
            )
        )
    return items


def detect_unused_dependencies(repo_dir: str) -> list[CleanupItem]:
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "deptry.json"
        if _tool(["deptry", ".", "--json-output", str(out_file)], repo_dir) is None:
            return []
        rows = json.loads(out_file.read_text()) if out_file.exists() else []
    items = []
    for r in rows:
        if r["error"]["code"] != "DEP002":
            continue
        unit = CodeUnit(r["location"]["file"], "dependency", r["module"])
        items.append(
            make_item(
                unit,
                "unused_dependency",
                "remove_dependency",
                "safe",
                f"{r['module']} is listed as a dependency but never imported.",
                [f"deptry DEP002: {r['error']['message']}"],
                ["deptry"],
            )
        )
    return items


def detect_security(repo_dir: str, graph, min_severity: str) -> list[CleanupItem]:
    out = _tool(["bandit", "-r", ".", "-f", "json", "-q"], repo_dir)
    if out is None or not out[1].strip():
        return []
    items = []
    for r in json.loads(out[1]).get("results", []):
        path = r["filename"].removeprefix("./")
        if _is_test(path) or SEVERITY[r["issue_severity"]] < SEVERITY[min_severity]:
            continue
        unit = _unit_at(graph, path, r["line_number"]) or CodeUnit(path, "file")
        items.append(
            make_item(
                unit,
                "security",
                "report_only",
                "suggest",
                f"Possible security problem: {r['issue_text']}",
                [f"bandit {r['test_id']} ({r['issue_severity']}) at line {r['line_number']}"],
                ["bandit"],
            )
        )
    return items


def detect_formatting(repo_dir: str) -> list[CleanupItem]:
    out = _tool(
        ["ruff", "format", "--isolated", "--check", "--output-format", "concise", "."], repo_dir
    )
    if out is None:
        return []
    items = []
    for line in out[1].splitlines():
        m = re.match(r"^(.+?\.py):\d+:\d+: unformatted", line.strip())
        if m:
            path = m.group(1).removeprefix("./")
            items.append(
                make_item(
                    CodeUnit(path, "file"),
                    "format",
                    "format",
                    "safe",
                    f"{path} does not follow the standard code format.",
                    ["ruff format --check would reformat this file"],
                    ["ruff"],
                )
            )
    return items


def detect_wrappers(repo_dir: str, graph) -> list[CleanupItem]:
    from cleansweep.analysis.features import is_wrapper_node

    from .rewrite import wrapper_patch

    items = []
    for unit in graph.units():
        mod = getattr(graph, "modules", {}).get(unit.path)
        node = mod.defs.get(unit.name) if (mod and unit.name) else None
        if node is None or not is_wrapper_node(node) or _is_test(unit.path):
            continue
        callers = [c for c in graph.callers(unit.key) if "::" in c]
        if len(callers) != 1:
            continue
        target = ast.unparse(node.body[-1].value.func)
        patch = wrapper_patch(repo_dir, graph, unit, node)
        evidence = [
            f"body is only `return {target}(...)` with the same arguments",
            f"called once, from {callers[0]}",
        ]
        if patch:
            items.append(
                make_item(
                    unit,
                    "wrapper",
                    "replace_with",
                    "safe",
                    f"{unit.name} only forwards to {target}; call it directly.",
                    evidence,
                    ["ast", "graph"],
                    patch=patch,
                )
            )
        else:
            items.append(
                make_item(
                    unit,
                    "wrapper",
                    "report_only",
                    "suggest",
                    f"{unit.name} only forwards to {target}.",
                    [*evidence, "rewrite too complex to do automatically"],
                    ["ast", "graph"],
                )
            )
    return items


def _keeper(graph, units: list[CodeUnit]) -> CodeUnit:
    def rank(u: CodeUnit):
        utils_like = any(w in u.path for w in ("util", "helper", "common"))
        return (-len(graph.callers(u.key)), not utils_like, u.name.startswith("_"), u.key)

    return sorted(units, key=rank)[0]


def detect_duplicates(
    repo_dir: str, graph, threshold: float, skip_paths: set[str]
) -> list[CleanupItem]:
    from cleansweep.analysis.minhash import body_text

    from .rewrite import duplicate_patch

    pairs = [
        (a, b, s)
        for a, b, s in find_duplicates(repo_dir, threshold)
        if a.path not in skip_paths and b.path not in skip_paths
    ]
    parent: dict[str, str] = {}
    units: dict[str, CodeUnit] = {}
    best: dict[tuple[str, str], float] = {}

    def find(k: str) -> str:
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k

    for a, b, sim in pairs:
        units[a.key], units[b.key] = a, b
        best[(a.key, b.key)] = best[(b.key, a.key)] = sim
        parent[find(a.key)] = find(b.key)
    groups: dict[str, list[CodeUnit]] = {}
    for key, unit in units.items():
        groups.setdefault(find(key), []).append(unit)

    items = []
    for members in groups.values():
        keep = _keeper(graph, members)
        keep_body = body_text(repo_dir, keep)
        for dup in members:
            if dup.key == keep.key:
                continue
            sim = best.get((dup.key, keep.key), 0.0)
            exact = body_text(repo_dir, dup) == keep_body
            evidence = [
                f"{'identical body' if exact else 'near-identical body'} to {keep.key} "
                f"(similarity {sim:.2f})"
            ]
            node = graph.modules[dup.path].defs.get(dup.name)
            patch = duplicate_patch(repo_dir, graph, dup, keep, node)
            if patch:
                items.append(
                    make_item(
                        dup,
                        "duplicate",
                        "replace_with",
                        "safe",
                        f"{dup.name} repeats {keep.name}; use the existing function instead.",
                        evidence,
                        ["minhash", "graph"],
                        keep_target=keep.key,
                        patch=patch,
                    )
                )
            else:
                items.append(
                    make_item(
                        dup,
                        "duplicate",
                        "report_only",
                        "suggest",
                        f"{dup.name} repeats {keep.name}.",
                        [*evidence, "used outside its file, so not rewritten automatically"],
                        ["minhash", "graph"],
                        keep_target=keep.key,
                    )
                )
    return items


def merge_items(items: list[CleanupItem]) -> list[CleanupItem]:
    """Merge items for the same unit, keeping the highest-priority category."""
    merged: dict[str, CleanupItem] = {}
    for item in sorted(items, key=lambda i: CATEGORY_PRIORITY.index(i.category)):
        if item.unit.key not in merged:
            merged[item.unit.key] = item
            continue
        first = merged[item.unit.key]
        first.evidence += [e for e in item.evidence if e not in first.evidence]
        first.sources += [s for s in item.sources if s not in first.sources]
    return list(merged.values())


def run_detectors(repo_dir: str, graph=None) -> list[CleanupItem]:
    """Run every static detector and return merged cleanup items."""
    cfg = _settings()
    graph = graph or build_graph(repo_dir)
    leftovers = detect_leftovers(repo_dir, graph, cfg["leftover_patterns"])
    deleted = {i.unit.path for i in leftovers}
    items = [
        *leftovers,
        *detect_dead_code(repo_dir, graph, cfg["vulture_min_confidence"]),
        *detect_unused_imports(repo_dir),
        *detect_unused_dependencies(repo_dir),
        *detect_security(repo_dir, graph, cfg["security_min_severity"]),
        *detect_formatting(repo_dir),
        *detect_wrappers(repo_dir, graph),
        *detect_duplicates(repo_dir, graph, cfg["duplicate_threshold"], deleted),
    ]
    # edits inside a file we are deleting anyway are noise
    items = [i for i in items if i.category == "leftover_file" or i.unit.path not in deleted]
    return merge_items(items)
