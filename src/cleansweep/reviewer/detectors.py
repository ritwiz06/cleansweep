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
    "judge_mode": "gatekeeper",
    "judge_batch_size": 10,
    "snippet_context_lines": 10,
    "overengineering": True,
    "overengineering_max_files": 20,
    "overengineering_budget_chars": 5000,
    "keep_public_api": "auto",
    "framework_callbacks": "on",
    "dynamic_refs": "on",
    "exclude": [],
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
PUBLIC_API_REASON = "public name with no caller in the project; may be public API"
# folders whose modules are run, not imported by users of the package
NOT_API_DIRS = {"scripts", "script", "examples", "example", "tests", "test", "docs", "benchmarks"}


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


def _settings(cfg: dict | None = None) -> dict:
    """Reviewer settings: DEFAULTS under the reviewer section of cfg, or of the config files when
    cfg has none."""
    if cfg is not None and "reviewer" in cfg:
        return {**DEFAULTS, **(cfg.get("reviewer") or {})}
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


def detect_leftovers(
    repo_dir: str, graph, patterns: list[str], only: set[str] | None = None
) -> list[CleanupItem]:
    from cleansweep.analysis.graph import name_in_configs

    root = Path(repo_dir)
    items = []
    files = sorted(root / f for f in only) if only is not None else sorted(root.rglob("*"))
    for p in files:
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


DEPENDENCY_FILE = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|setup\.(py|cfg))$")


def detect_agent_scratch(repo_dir: str, graph, scope) -> list[CleanupItem]:
    """Files the agent created outside the project (repo root or a new folder) that nothing
    else imports: reproduction scripts, scratch tests, throwaway sample projects."""
    from cleansweep.analysis.graph import module_in_configs

    scratch = {f for f in scope.files_added if scope.outside_project(f)}
    # files that existed before the patch and weren't touched by it can't need these new ones
    can_import = scope.files - scratch
    items = []
    for path in sorted(scratch):
        importers = set(getattr(graph, "imported_by", {}).get(path, ())) & can_import
        if importers or module_in_configs(repo_dir, path):
            continue
        items.append(
            make_item(
                CodeUnit(path, "file"),
                "leftover_file",
                "delete_file",
                "safe",
                f"{path} was created by the agent outside the project's code, and nothing "
                "in the project imports it.",
                [
                    "added by the agent patch at the repo root or in a folder it created",
                    "no project file imports it",
                    "not mentioned in project config files",
                ],
                ["scope", "graph"],
            )
        )
    return items


VULTURE_LINE = re.compile(
    r"^(.+?):(\d+): unused (function|method|class) '([^']+)' \((\d+)% confidence"
)


def detect_dead_code(
    repo_dir: str, graph, min_conf: int, paths: set[str] | None = None
) -> list[CleanupItem]:
    # vulture needs the whole project to see every use; `paths` only filters its report
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
        if _is_test(path) or (paths is not None and path not in paths):
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


def has_package_metadata(repo_dir: str) -> bool:
    """A setup.py, a setup.cfg with [metadata] or [options], or a pyproject.toml with a [project]
    or [tool.poetry] table: the repository is published as a package."""
    import tomllib

    root = Path(repo_dir)
    if (root / "setup.py").exists():
        return True
    setup_cfg = root / "setup.cfg"
    if setup_cfg.exists() and re.search(
        r"^\[(metadata|options)\]", setup_cfg.read_text(errors="replace"), re.MULTILINE
    ):
        return True
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return "project" in data or "poetry" in data.get("tool", {})


def is_public_api(repo_dir: str, unit: CodeUnit) -> bool:
    """A function or class whose qualified name has no leading underscore, in a module of an
    importable package (a folder with an __init__.py and a valid module name), and not in a test,
    script or example folder, a __main__.py or a private _module."""
    if unit.kind not in ("function", "class") or not unit.name:
        return False
    if any(part.startswith("_") for part in unit.name.split(".")):
        return False
    path = Path(unit.path)
    if _is_test(unit.path) or path.suffix != ".py" or path.stem.startswith("_"):
        return False
    if any(part in NOT_API_DIRS for part in path.parts[:-1]):
        return False
    folder = path.parent
    return folder.name.isidentifier() and (Path(repo_dir) / folder / "__init__.py").exists()


def keep_public_api(
    items: list[CleanupItem], repo_dir: str, setting: str | None = None
) -> list[CleanupItem]:
    """reviewer.keep_public_api: "on" moves dead-code items on public names in package modules
    (is_public_api) to the suggest lane, "off" never does, "auto" (default) only when the
    repository has packaging metadata. With no caller in the project, the Guard's tests and probes
    have nothing to run, so only the owner can tell whether such a name is used outside."""
    if setting is None:
        setting = _settings().get("keep_public_api", "auto")
    setting = {True: "on", False: "off"}.get(setting, setting)  # YAML reads bare on/off as bools
    if setting not in ("auto", "on", "off"):
        raise ValueError(f"reviewer.keep_public_api must be auto, on or off, got {setting!r}")
    if setting == "off" or (setting == "auto" and not has_package_metadata(repo_dir)):
        return items
    for item in items:
        if item.category != "dead_code" or not is_public_api(repo_dir, item.unit):
            continue
        if item.lane == "safe":
            item.lane, item.reason = "suggest", PUBLIC_API_REASON
        item.evidence.append(f"public API policy: {PUBLIC_API_REASON}")
    return items


FRAMEWORK_REASON = "{framework} calls this method by name; nothing in the project calls it"


def keep_framework_callbacks(
    items: list[CleanupItem], graph, setting: str | None = None
) -> list[CleanupItem]:
    """reviewer.framework_callbacks: "on" (default) moves dead-code and duplicate items on methods
    a framework calls by name (analysis/frameworks.py) to the suggest lane, "off" never does. With
    no caller in the project, neither the graph nor the Guard can see that they are used."""
    if setting is None:
        setting = _settings().get("framework_callbacks", "on")
    if not is_on("framework_callbacks", setting) or graph is None:
        return items
    for item in items:
        framework = graph.framework_callback(item.unit.key)
        if item.category not in ("dead_code", "duplicate") or framework is None:
            continue
        reason = FRAMEWORK_REASON.format(framework=framework)
        if item.lane == "safe":
            item.lane, item.reason = "suggest", reason
        item.evidence.append(f"framework callback: {reason}")
    return items


DYNAMIC_REFS_REASON = "reached by name ({evidence}); nothing in the project calls it"


def is_on(name: str, setting) -> bool:
    """A reviewer on/off setting as a bool (YAML reads bare on/off as booleans)."""
    setting = {True: "on", False: "off"}.get(setting, setting)
    if setting not in ("on", "off"):
        raise ValueError(f"reviewer.{name} must be on or off, got {setting!r}")
    return setting == "on"


def dynamic_refs_on(cfg: dict | None = None) -> bool:
    """reviewer.dynamic_refs of a run's config (or of the config files)."""
    return is_on("dynamic_refs", _settings(cfg).get("dynamic_refs", "on"))


def keep_dynamic_refs(items: list[CleanupItem], graph, setting=None) -> list[CleanupItem]:
    """reviewer.dynamic_refs: "on" (default) moves dead-code and duplicate items on units that
    something reaches by name (analysis/dynamic_refs.py: entry points, config files, registries,
    __all__, getattr strings, __subclasses__, framework base classes) to the suggest lane, with
    the evidence; "off" never does. The agent team's Auditor applies it; v1's plan does not."""
    if setting is None:
        setting = _settings().get("dynamic_refs", "on")
    if not is_on("dynamic_refs", setting) or graph is None:
        return items
    for item in items:
        if item.category not in ("dead_code", "duplicate"):
            continue
        refs = graph.dynamic_refs(item.unit.key)
        if not refs:
            continue
        if item.lane == "safe":
            item.lane, item.reason = "suggest", DYNAMIC_REFS_REASON.format(evidence=refs[0])
        item.evidence += [f"reached by name: {r}" for r in refs]
    return items


def excluded(path: str, prefixes: list[str]) -> bool:
    """reviewer.exclude: folders (or files) the Reviewer leaves alone, e.g. ["tests/fixtures/"]."""
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def detect_unused_imports(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    if paths == []:
        return []
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
            *(paths or ["."]),
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
                [
                    f"deptry DEP002: {r['error']['message']}",
                    *_dependency_mentions(repo_dir, r["module"], unit.path),
                ],
                ["deptry"],
            )
        )
    return items


# Files where a package can be used without a Python import (CLI tools, CI steps).
DEPENDENCY_CONFIGS = [
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "noxfile.py",
    "Makefile",
    "Dockerfile",
    ".pre-commit-config.yaml",
]


def _dependency_mentions(repo_dir: str, package: str, declared_in: str) -> list[str]:
    root = Path(repo_dir)
    candidates = [root / name for name in DEPENDENCY_CONFIGS]
    candidates += sorted((root / ".github" / "workflows").glob("*.y*ml"))
    candidates += sorted(root.glob("*.sh"))
    pattern = re.compile(rf"(?<![\w-]){re.escape(package)}(?![\w-])", re.IGNORECASE)
    found = []
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if (
            rel != declared_in
            and path.is_file()
            and pattern.search(path.read_text(errors="replace"))
        ):
            found.append(rel)
    if found:
        return [f"{package} is mentioned in {', '.join(found)}"]
    return [f"{package} is not mentioned in any config, CI or script file"]


def detect_security(
    repo_dir: str, graph, min_severity: str, paths: list[str] | None = None, scope=None
) -> list[CleanupItem]:
    if paths == []:
        return []
    out = _tool(["bandit", "-r", *(paths or ["."]), "-f", "json", "-q"], repo_dir)
    if out is None or not out[1].strip():
        return []
    items = []
    for r in json.loads(out[1]).get("results", []):
        path = r["filename"].removeprefix("./")
        if _is_test(path) or SEVERITY[r["issue_severity"]] < SEVERITY[min_severity]:
            continue
        if scope is not None and not scope.covers_line(path, r["line_number"]):
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


def detect_formatting(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    from cleansweep.analysis.graph import ruff_isolation

    if paths == []:
        return []
    out = _tool(
        [
            "ruff",
            "format",
            *ruff_isolation(repo_dir),
            "--check",
            "--output-format",
            "concise",
            *(paths or ["."]),
        ],
        repo_dir,
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


def _keeper(graph, units: list[CodeUnit], scope=None) -> CodeUnit:
    def rank(u: CodeUnit):
        utils_like = any(w in u.path for w in ("util", "helper", "common"))
        mine = scope is not None and scope.covers(u)  # keep existing code over the agent's copy
        return (mine, -len(graph.callers(u.key)), not utils_like, u.name.startswith("_"), u.key)

    return sorted(units, key=rank)[0]


def detect_duplicates(
    repo_dir: str, graph, threshold: float, skip_paths: set[str], scope=None
) -> list[CleanupItem]:
    from cleansweep.analysis.minhash import body_text

    from .rewrite import duplicate_patch

    pairs = [
        (a, b, s)
        for a, b, s in find_duplicates(
            repo_dir, threshold, only=scope.units if scope is not None else None
        )
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
        keep = _keeper(graph, members, scope)
        keep_body = body_text(repo_dir, keep)
        for dup in members:
            if dup.key == keep.key or (scope is not None and not scope.covers(dup)):
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


def run_detectors(repo_dir: str, graph=None, scope=None, cfg=None) -> list[CleanupItem]:
    """Run every static detector and return merged cleanup items.

    With an AgentScope (cleansweep.analysis.scope), only what the agent wrote is reviewed:
    leftover files among the files it created, formatting of those files, and the other
    detectors on the units and lines it added or changed.
    """
    cfg = _settings(cfg)
    graph = graph or build_graph(repo_dir)
    agent_py = sorted(f for f in scope.files if f.endswith(".py")) if scope else None
    new_py = sorted(f for f in scope.files_added if f.endswith(".py")) if scope else None
    leftovers = detect_leftovers(
        repo_dir, graph, cfg["leftover_patterns"], only=scope.files_added if scope else None
    )
    if scope is not None:
        named = {i.unit.path for i in leftovers}
        leftovers += [
            i for i in detect_agent_scratch(repo_dir, graph, scope) if i.unit.path not in named
        ]
    deleted = {i.unit.path for i in leftovers}
    touches_deps = scope is None or any(DEPENDENCY_FILE.search(f) for f in scope.files)
    items = [
        *leftovers,
        *detect_dead_code(
            repo_dir, graph, cfg["vulture_min_confidence"], set(agent_py) if scope else None
        ),
        *detect_unused_imports(repo_dir, agent_py),
        *(detect_unused_dependencies(repo_dir) if touches_deps else []),
        *detect_security(repo_dir, graph, cfg["security_min_severity"], agent_py, scope),
        *detect_formatting(repo_dir, new_py),
        *detect_wrappers(repo_dir, graph),
        *detect_duplicates(repo_dir, graph, cfg["duplicate_threshold"], deleted, scope),
    ]
    if scope is not None:
        items = [i for i in items if scope.covers(i.unit)]
    # edits inside a file we are deleting anyway are noise
    items = [i for i in items if i.category == "leftover_file" or i.unit.path not in deleted]
    return merge_items(items)
