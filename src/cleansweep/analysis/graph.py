from __future__ import annotations

import ast
import os
import re
import tomllib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from cleansweep.analysis.frameworks import framework_for, is_callback_name
from cleansweep.core.models import CodeUnit

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
    ".cleansweep",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}
ENTRY_DECORATORS = {
    "route",
    "command",
    "fixture",
    "register",
    "task",
    "receiver",
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "group",
    "callback",
    "listener",
    "handler",
}
DYNAMIC_CALLS = {"getattr", "__import__", "globals", "import_module"}


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    parts = path.split("/")[:-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "tests" in parts
        or "test" in parts
    )


def iter_py_files(repo_dir: str | Path) -> list[str]:
    """Repo-relative paths of .py files, skipping .git, virtualenvs and build folders."""
    root = Path(repo_dir)
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)  # prune: never walk .git
        rel = Path(folder).relative_to(root)
        found += [(rel / f).as_posix() for f in files if f.endswith(".py")]
    return sorted(found, key=lambda p: Path(p).parts)  # same order as before


def module_name(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


@dataclass
class _Module:
    path: str
    name: str
    tree: ast.Module | None
    defs: dict[str, ast.AST] = field(default_factory=dict)  # qualname -> node
    aliases: dict[str, tuple] = field(default_factory=dict)  # local name -> target
    uses_dynamic: bool = False
    has_getattr_hook: bool = False


class CodeGraph:
    """Files, classes and functions of a repo, with reference edges and entry points."""

    def __init__(self, repo_dir: str):
        self.repo_dir = str(repo_dir)
        self._units: dict[str, CodeUnit] = {}
        self._out: dict[str, set[str]] = defaultdict(set)
        self._in: dict[str, set[str]] = defaultdict(set)
        self.imported_by: dict[str, set[str]] = defaultdict(set)  # file -> files importing it
        self.entries: set[str] = set()
        self.modules: dict[str, _Module] = {}
        self._reachable: set[str] = set()
        self._dynamic: set[str] = set()
        self._framework: dict[str, str] = {}  # method key -> framework that calls it by name
        self._dyn_modules: set[str] = set()
        self._strings: set[str] = set()
        self._prefixes: set[str] = set()

    def units(self) -> list[CodeUnit]:
        """All file, class and function units."""
        return list(self._units.values())

    def unit(self, key: str) -> CodeUnit | None:
        return self._units.get(key)

    def callers(self, unit_key: str) -> list[str]:
        """Units that reference this unit (calls, imports, attribute use)."""
        return sorted(self._in.get(unit_key, ()))

    def callees(self, unit_key: str) -> list[str]:
        """Units this unit references."""
        return sorted(self._out.get(unit_key, ()))

    def is_reachable(self, unit_key: str) -> bool:
        """True if the unit can be reached from an entry point (tests, __main__, scripts)."""
        return unit_key in self._reachable

    def dynamic_risk(self, unit_key: str) -> bool:
        """True if the unit might be used in ways the static graph can't see."""
        return unit_key in self._dynamic

    def framework_callback(self, unit_key: str) -> str | None:
        """The framework that calls this method by name (see analysis/frameworks.py), or None."""
        return self._framework.get(unit_key)

    def file_of(self, unit_key: str) -> str:
        return unit_key.split("::", 1)[0]

    def _edge(self, src: str, dst: str) -> None:
        if src != dst and dst in self._units:
            self._out[src].add(dst)
            self._in[dst].add(src)


def _resolve_relative(mod: _Module, level: int, target: str | None) -> str:
    parts = mod.name.split(".")
    is_pkg = mod.path.endswith("__init__.py")
    base = parts if is_pkg else parts[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, target] if target else base)


def _collect_defs(mod: _Module) -> None:
    for node in mod.tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            mod.defs[node.name] = node
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                        mod.defs[f"{node.name}.{sub.name}"] = sub


def _collect_aliases(mod: _Module, known: set[str]) -> None:
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    mod.aliases[a.asname] = ("module", a.name)
                else:
                    top = a.name.split(".")[0]
                    mod.aliases[top] = ("module", top)
        elif isinstance(node, ast.ImportFrom):
            src = _resolve_relative(mod, node.level, node.module) if node.level else node.module
            for a in node.names:
                local = a.asname or a.name
                if f"{src}.{a.name}" in known:
                    mod.aliases[local] = ("module", f"{src}.{a.name}")
                else:
                    mod.aliases[local] = ("name", src, a.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name | ast.Attribute):
            fname = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if fname in DYNAMIC_CALLS:
                mod.uses_dynamic = True
    mod.has_getattr_hook = "__getattr__" in mod.defs


def build_graph(repo_dir: str) -> CodeGraph:
    """Parse every .py file and build the reference graph."""
    g = CodeGraph(repo_dir)
    root = Path(repo_dir)
    files = iter_py_files(root)
    by_name: dict[str, _Module] = {}
    for path in files:
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            tree = None
        mod = _Module(path=path, name=module_name(path), tree=tree)
        g.modules[path] = mod
        by_name[mod.name] = mod
        end = len(tree.body) and tree.body[-1].end_lineno if tree else None
        g._units[path] = CodeUnit(path=path, kind="file", start_line=1, end_line=end)
    known = set(by_name)
    for mod in g.modules.values():
        if mod.tree is None:
            continue
        _collect_defs(mod)
        _collect_aliases(mod, known)
        for qual, node in mod.defs.items():
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            g._units[f"{mod.path}::{qual}"] = CodeUnit(mod.path, kind, qual, start, node.end_lineno)

    method_names: dict[str, list[str]] = defaultdict(list)
    for key, unit in g._units.items():
        if unit.kind == "function" and unit.name and "." in unit.name:
            method_names[unit.name.split(".")[-1]].append(key)

    for mod in g.modules.values():
        if mod.tree is not None:
            _add_edges(g, mod, by_name, method_names)
    _find_entries(g, root)
    _find_dynamic(g, by_name)
    _find_framework_callbacks(g, by_name)
    _compute_reachable(g)
    return g


def _target_key(by_name: dict[str, _Module], module: str, name: str | None = None) -> str | None:
    mod = by_name.get(module)
    if mod is None:
        return None
    if name is None:
        return mod.path
    return f"{mod.path}::{name}" if name in mod.defs else None


def _add_edges(g: CodeGraph, mod: _Module, by_name: dict, method_names: dict) -> None:
    for alias in mod.aliases.values():
        target_mod = alias[1]
        if target_mod in by_name:
            dst = by_name[target_mod].path
            g._edge(mod.path, dst)
            g.imported_by[dst].add(mod.path)
            if alias[0] == "name" and (key := _target_key(by_name, target_mod, alias[2])):
                g._edge(mod.path, key)

    def resolve_name(name: str) -> str | None:
        if name in mod.defs:
            return f"{mod.path}::{name}"
        alias = mod.aliases.get(name)
        if alias is None:
            return None
        if alias[0] == "module":
            return _target_key(by_name, alias[1])
        return _target_key(by_name, alias[1], alias[2]) or _target_key(by_name, alias[1])

    def refs(node: ast.AST, owner: str, cls: str | None) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if key := resolve_name(sub.id):
                    g._edge(owner, key)
            elif isinstance(sub, ast.Attribute):
                base = sub.value
                if isinstance(base, ast.Name) and base.id in ("self", "cls") and cls:
                    g._edge(owner, f"{mod.path}::{cls}.{sub.attr}")
                    continue
                if isinstance(base, ast.Name) and (alias := mod.aliases.get(base.id)):
                    if alias[0] == "module":
                        key = _target_key(by_name, alias[1], sub.attr) or _target_key(
                            by_name, f"{alias[1]}.{sub.attr}"
                        )
                        if key:
                            g._edge(owner, key)
                            continue
                # unknown receiver: link to every method with this name (over-approximate)
                for key in method_names.get(sub.attr, ()):
                    g._edge(owner, key)

    def walk_body(body: list[ast.stmt], owner: str, cls: str | None) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qual = f"{cls}.{stmt.name}" if cls else stmt.name
                key = f"{mod.path}::{qual}"
                for dec in stmt.decorator_list:
                    refs(dec, owner, cls)
                if key not in g._units:  # nested def: attribute to the outer owner
                    refs(stmt, owner, cls)
                elif isinstance(stmt, ast.ClassDef):
                    for b in stmt.bases:
                        refs(b, key, None)
                    walk_body(stmt.body, key, stmt.name)
                else:
                    refs(stmt.args, owner, cls)
                    for s in stmt.body:
                        refs(s, key, cls)
            else:
                refs(stmt, owner, cls)

    walk_body(mod.tree.body, mod.path, None)


def _decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return dec.id if isinstance(dec, ast.Name) else ""


def _find_entries(g: CodeGraph, root: Path) -> None:
    for path, mod in g.modules.items():
        if is_test_file(path):
            g.entries.update(k for k in g._units if g.file_of(k) == path)
            continue
        if path.endswith("__main__.py"):
            g.entries.add(path)
        if mod.tree is None:
            continue
        for node in mod.tree.body:
            if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
                g.entries.add(path)
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                for elt in getattr(node.value, "elts", []):
                    if isinstance(elt, ast.Constant) and elt.value in mod.defs:
                        g.entries.add(f"{path}::{elt.value}")
        for qual, node in mod.defs.items():
            decs = {_decorator_name(d) for d in getattr(node, "decorator_list", [])}
            if decs & ENTRY_DECORATORS:
                g.entries.add(f"{path}::{qual}")
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            scripts = tomllib.loads(pyproject.read_text()).get("project", {}).get("scripts", {})
        except tomllib.TOMLDecodeError:
            scripts = {}
        by_name = {m.name: m for m in g.modules.values()}
        for spec in scripts.values():
            module, _, func = spec.partition(":")
            if key := _target_key(by_name, module.strip(), func.strip() or None):
                g.entries.add(key)


def _find_dynamic(g: CodeGraph, by_name: dict[str, _Module]) -> None:
    for mod in g.modules.values():
        if mod.tree is None:
            continue
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                g._strings.add(node.value)
            elif isinstance(node, ast.JoinedStr) and node.values:
                first = node.values[0]
                if isinstance(first, ast.Constant) and len(str(first.value)) >= 3:
                    g._prefixes.add(str(first.value))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and not isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[0], ast.Name)
            ):
                alias = mod.aliases.get(node.args[0].id)
                if alias and alias[0] == "module" and alias[1] in by_name:
                    g._dyn_modules.add(by_name[alias[1]].path)
    for key, unit in g._units.items():
        mod = g.modules[unit.path]
        name = (unit.name or module_name(unit.path)).split(".")[-1]
        node = mod.defs.get(unit.name) if unit.name else None
        if (
            name in g._strings
            or module_name(unit.path) in g._strings
            or any(name.startswith(p) for p in g._prefixes)
            or (unit.name and mod.uses_dynamic)
            or mod.has_getattr_hook
            or (node is not None and getattr(node, "decorator_list", None))
            or (unit.name and unit.path in g._dyn_modules)
        ):
            g._dynamic.add(key)


def _class_framework(
    mod: _Module, name: str, by_name: dict[str, _Module], seen: set[tuple[str, str]]
) -> str | None:
    """The framework a class inherits from, following bases through the project's modules."""
    node = mod.defs.get(name)
    if not isinstance(node, ast.ClassDef) or (mod.path, name) in seen:
        return None
    seen.add((mod.path, name))
    for base in node.bases:
        base = base.value if isinstance(base, ast.Subscript) else base  # Screen[None]
        if not isinstance(base, ast.Name | ast.Attribute):
            continue
        head, *rest = ast.unparse(base).split(".")
        alias = mod.aliases.get(head)
        if alias is None:
            found = _class_framework(mod, head, by_name, seen) if not rest else None
        elif alias[0] == "module":
            module = ".".join([alias[1], *rest[:-1]])
            if module in by_name:
                found = _class_framework(by_name[module], rest[-1] if rest else "", by_name, seen)
            else:
                found = framework_for(module)
        elif alias[1] in by_name:
            found = _class_framework(by_name[alias[1]], alias[2], by_name, seen)
        else:
            found = framework_for(alias[1] or "")
        if found:
            return found
    return None


def _find_framework_callbacks(g: CodeGraph, by_name: dict[str, _Module]) -> None:
    for mod in g.modules.values():
        for qual, node in mod.defs.items():
            if not isinstance(node, ast.ClassDef):
                continue
            framework = _class_framework(mod, qual, by_name, set())
            if framework is None:
                continue
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef) and is_callback_name(
                    framework, sub.name
                ):
                    g._framework[f"{mod.path}::{qual}.{sub.name}"] = framework


def _compute_reachable(g: CodeGraph) -> None:
    seen = set(g.entries)
    queue = deque(seen)
    while queue:
        key = queue.popleft()
        nxt = set(g._out.get(key, ()))
        unit = g._units.get(key)
        if unit and unit.name:
            nxt.add(unit.path)  # using a def means its module was imported
            if unit.kind == "class":
                nxt.update(k for k in g._units if k.startswith(f"{key}.__"))
        for k in nxt:
            if k not in seen:
                seen.add(k)
                queue.append(k)
    g._reachable = seen


CONFIG_FILES = (
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "Makefile",
    "Dockerfile",
    "noxfile.py",
    ".pre-commit-config.yaml",
)


def ruff_isolation(repo_dir: str) -> list[str]:
    """[] if the project configures ruff itself (ruff.toml, .ruff.toml, [tool.ruff]), else
    ["--isolated"]: format edits follow the project's own line length when it sets one."""
    root = Path(repo_dir)
    if (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
        return []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and "[tool.ruff" in pyproject.read_text(errors="replace"):
        return []
    return ["--isolated"]


def name_in_configs(repo_dir: str, path: str) -> bool:
    """True if a file name is mentioned in config files (setup.cfg, pyproject, Makefile...)."""
    root = Path(repo_dir)
    stem = Path(path).stem
    for cfg in CONFIG_FILES:
        p = root / cfg
        if p.exists() and re.search(rf"\b{re.escape(stem)}\b", p.read_text(errors="replace")):
            return True
    return False


def import_name(path: str) -> str:
    """The dotted name a file is imported by (src layout aware), e.g. pkg.sub.mod."""
    return module_name(path.removeprefix("src/"))


def module_in_configs(repo_dir: str, path: str) -> bool:
    """True if config files name this file by its import name or its path. Stricter than
    name_in_configs: a bare file name like "admin" or "tests" does not count."""
    root = Path(repo_dir)
    names = {import_name(path), path}
    for cfg in CONFIG_FILES:
        p = root / cfg
        if not p.exists():
            continue
        text = p.read_text(errors="replace")
        if any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", text) for n in names):
            return True
    return False
