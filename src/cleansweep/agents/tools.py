"""Tool registry: the agents' tools, each a thin wrapper over existing CleanSweep code."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cleansweep.analysis.graph import is_test_file
from cleansweep.analysis.minhash import _normalized_tokens, _shingles, body_text
from cleansweep.reviewer.detectors import _dependency_mentions

from .secrets import is_secret_file

MAX_LINES = 120
MAX_HITS = 12
WITHHELD = "[withheld: this file may hold secrets]"
S = {"type": "string"}
INT = {"type": "integer", "minimum": 1}


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    required: list[str]
    fn: Callable[..., str]

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": self.params,
            "required": self.required,
            "additionalProperties": False,
        }


class ToolSet:
    """A named set of tools an agent may call."""

    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def describe(self) -> str:
        return "\n".join(
            f"- {t.name}: {t.description} args={json.dumps(t.params)} required={t.required}"
            for t in self.tools.values()
        )

    def schemas(self) -> dict[str, dict]:
        return {name: t.schema() for name, t in self.tools.items()}

    def subset(self, names: list[str]) -> ToolSet:
        return ToolSet([self.tools[n] for n in names if n in self.tools])

    def call(self, name: str, args: dict) -> str:
        """Run a tool; an error comes back as text the agent can read."""
        try:
            return str(self.tools[name].fn(**args))
        except Exception as exc:  # a tool error is an observation, not a crash
            return f"error: {type(exc).__name__}: {str(exc)[:300]}"


def _grep(repo_dir: str, name: str) -> list[tuple[str, int, str]]:
    proc = subprocess.run(
        ["git", "grep", "-n", "-I", "-w", "-F", "--", name],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    hits = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        num, _, text = rest.partition(":")
        if num.isdigit() and not is_secret_file(path):
            hits.append((path, int(num), text.strip()))
    return hits


def _units_named(graph, name: str) -> list[str]:
    return [
        u.key for u in graph.units() if u.name and (u.name == name or u.name.split(".")[-1] == name)
    ]


def find_references(rt, name: str, include_tests: bool = True) -> str:
    keys = _units_named(rt.graph, name)
    callers = sorted({c for k in keys for c in rt.graph.callers(k)})
    defining = re.compile(rf"^\s*(async\s+def|def|class)\s+{re.escape(name)}\b")
    code, tests, other = [], [], []
    for path, num, text in _grep(rt.ws.path, name):
        if defining.match(text):
            continue
        where = f"{path}:{num}"
        if path.endswith(".py") and is_test_file(path):
            tests.append(where)
        elif path.endswith(".py"):
            code.append(where)
        else:
            other.append(where)
    if not include_tests:
        tests = []
    parts = [
        f"units named {name}: {keys or 'none'}",
        f"graph callers: {callers[:MAX_HITS] or 'none'}",
        f"text matches in code: {len(code)} {code[:MAX_HITS]}",
        f"in tests: {len(tests)} {tests[:MAX_HITS]}",
        f"in other files (docs, configs): {len(other)} {other[:MAX_HITS]}",
    ]
    return "\n".join(parts)


def read_code(rt, path: str, start_line: int, end_line: int) -> str:
    if is_secret_file(path):
        return WITHHELD
    file = (Path(rt.ws.path) / path).resolve()
    if not str(file).startswith(str(Path(rt.ws.path).resolve())) or not file.is_file():
        return f"no file {path}"
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, start_line)
    end = min(len(lines), end_line, start + MAX_LINES - 1)
    body = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
    return f"{path} lines {start}-{end} of {len(lines)}\n{body}"


def _all_names(repo_dir: str, path: str) -> set[str]:
    try:
        tree = ast.parse((Path(repo_dir) / path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            try:
                return set(ast.literal_eval(node.value))
            except ValueError:
                return set()
    return set()


def check_dynamic_use(rt, name: str) -> str:
    keys = _units_named(rt.graph, name)
    rows = []
    for key in keys:
        path = rt.graph.file_of(key)
        rows.append(
            f"{key}: dynamic risk {'yes' if rt.graph.dynamic_risk(key) else 'no'}; "
            f"framework callback {rt.graph.framework_callback(key) or 'no'}; "
            f"reachable from an entry point {'yes' if rt.graph.is_reachable(key) else 'no'}; "
            f"in __all__ {'yes' if name in _all_names(rt.ws.path, path) else 'no'}"
        )
    quoted = [
        f"{p}:{n}"
        for p, n, t in _grep(rt.ws.path, name)
        if f'"{name}"' in t or f"'{name}'" in t or "getattr(" in t
    ]
    rows.append(f"string or getattr mentions: {len(quoted)} {quoted[:MAX_HITS]}")
    return "\n".join(rows) if keys else f"no unit named {name}\n" + rows[-1]


def find_related_tests(rt, path: str) -> str:
    stem = Path(path).stem
    importers = sorted(rt.graph.imported_by.get(path, set()))
    tests = [p for p in importers if is_test_file(p)]
    named = [
        u.path
        for u in rt.graph.units()
        if u.kind == "file"
        and is_test_file(u.path)
        and Path(u.path).stem in (f"test_{stem}", f"{stem}_test")
    ]
    found = sorted(set(tests + named))
    return f"tests related to {path}: {found or 'none found'}"


def related_tests(graph, paths: list[str]) -> list[str]:
    """Test files that import or are named after any of the given files."""
    out: set[str] = set()
    for path in paths:
        stem = Path(path).stem
        out |= {p for p in graph.imported_by.get(path, set()) if is_test_file(p)}
        out |= {
            u.path
            for u in graph.units()
            if u.kind == "file"
            and is_test_file(u.path)
            and Path(u.path).stem in (f"test_{stem}", f"{stem}_test")
        }
    return sorted(out)


def check_dependency_usage(rt, package: str) -> str:
    module = package.lower().replace("-", "_")
    imports = [
        f"{p}:{n}"
        for p, n, t in _grep(rt.ws.path, module)
        if p.endswith(".py") and re.match(rf"\s*(import|from)\s+{re.escape(module)}\b", t)
    ]
    declared = next(
        (
            f
            for f in ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt")
            if (Path(rt.ws.path) / f).exists()
        ),
        "",
    )
    mentions = _dependency_mentions(rt.ws.path, package, declared)
    return f"imports of {module}: {len(imports)} {imports[:MAX_HITS]}\n" + "\n".join(mentions)


def compare_functions(rt, a: str, b: str) -> str:
    ua, ub = rt.graph.unit(a), rt.graph.unit(b)
    if ua is None or ub is None:
        return f"unknown unit: {a if ua is None else b} (use keys like path.py::name)"
    sa, sb = body_text(rt.ws.path, ua), body_text(rt.ws.path, ub)
    try:
        same_ast = ast.dump(ast.parse(sa)) == ast.dump(ast.parse(sb))
    except SyntaxError:
        same_ast = False
    ka, kb = _shingles(_normalized_tokens(sa)), _shingles(_normalized_tokens(sb))
    sim = len(ka & kb) / len(ka | kb) if ka | kb else 0.0
    ast_text = "IDENTICAL" if same_ast else "DIFFERENT (the code or its constants differ)"
    return f"AST: {ast_text}; token similarity {sim:.2f} (names and literals ignored)"


def query_lessons(rt, pattern: str) -> str:
    found = rt.lessons.search(pattern)
    if not found:
        return "no lessons match"
    return "\n".join(
        f"{les['lesson_id']}: {les['reason']} (pattern {les['pattern']})" for les in found
    )


def query_knowledge_base(
    rt, category: str, framework: str = "", agent: str = "", file_pattern: str = ""
) -> str:
    return rt.kb.query(
        category=category, framework=framework, agent=agent, file_pattern=file_pattern
    )


def read_artifact(rt, art_id: str, start_line: int = 1, end_line: int = 80) -> str:
    return rt.cache.slice(art_id, start_line, end_line)


def investigation_tools(rt) -> ToolSet:
    """The Investigator's tools, bound to a run."""

    def bind(fn):
        return lambda **args: fn(rt, **args)

    return ToolSet(
        [
            Tool(
                "find_references",
                "Every reference to a name: code-graph callers and text matches in code, "
                "tests and other files.",
                {"name": S, "include_tests": {"type": "boolean"}},
                ["name"],
                bind(find_references),
            ),
            Tool(
                "read_code",
                "Read lines of a file (at most 120).",
                {"path": S, "start_line": INT, "end_line": INT},
                ["path", "start_line", "end_line"],
                bind(read_code),
            ),
            Tool(
                "check_dynamic_use",
                "Dynamic risk, framework callbacks, reachability, __all__ and "
                "string/getattr mentions of a name.",
                {"name": S},
                ["name"],
                bind(check_dynamic_use),
            ),
            Tool(
                "find_related_tests",
                "Test files that import or are named after a file.",
                {"path": S},
                ["path"],
                bind(find_related_tests),
            ),
            Tool(
                "check_dependency_usage",
                "Imports of a declared package and mentions in configs, CI and scripts.",
                {"package": S},
                ["package"],
                bind(check_dependency_usage),
            ),
            Tool(
                "compare_functions",
                "Compare two functions by unit key (path.py::name): same AST and token similarity.",
                {"a": S, "b": S},
                ["a", "b"],
                bind(compare_functions),
            ),
            Tool(
                "query_lessons",
                "Lessons written after earlier rollbacks in this run that match a word, "
                "name or category.",
                {"pattern": S},
                ["pattern"],
                bind(query_lessons),
            ),
            Tool(
                "query_knowledge_base",
                "Mined slop rules, review-comment clusters and framework conventions "
                "for a category.",
                {"category": S, "framework": S, "agent": S, "file_pattern": S},
                ["category"],
                bind(query_knowledge_base),
            ),
            Tool(
                "read_artifact",
                "Read lines of a cached artifact by its ID.",
                {"art_id": S, "start_line": INT, "end_line": INT},
                ["art_id"],
                bind(read_artifact),
            ),
        ]
    )


__all__ = ["Tool", "ToolSet", "investigation_tools", "related_tests"]
