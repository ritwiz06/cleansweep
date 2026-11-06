"""Units a project reaches by name, which the static graph sees no call to.

A unit counts as used when something can reach it by name: an entry point or build hook in the
packaging metadata, a dotted name in a config file or a settings list, a decorator registry,
__all__, getattr or import_module with a literal string, __subclasses__() discovery, or a base
class whose subclasses a framework finds by itself (analysis/frameworks.py). The resolver
returns, per unit key, one evidence line for each way; it changes nothing in the graph.
"""

from __future__ import annotations

import ast
import configparser
import os
import re
import tomllib
from collections import defaultdict, deque
from pathlib import Path

from .frameworks import discovered_base, module_hook
from .graph import SKIP_DIRS, CodeGraph, _Module, external_bases, import_name

CONFIG_SUFFIXES = (".toml", ".yaml", ".yml", ".json", ".ini", ".cfg")
MAX_CONFIG_BYTES = 1_000_000
NAME = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
TOKEN = re.compile(rf"(?<![\w./:-])({NAME})(?::({NAME}))?(?![\w/-])")
FULL = re.compile(rf"({NAME})(?::({NAME}))?")
PEP517_HOOKS = {
    "build_wheel",
    "build_sdist",
    "build_editable",
    "get_requires_for_build_wheel",
    "get_requires_for_build_sdist",
    "get_requires_for_build_editable",
    "prepare_metadata_for_build_wheel",
    "prepare_metadata_for_build_editable",
}
# decorators that register the function under its name (bare, or the last part of x.y)
REGISTRY_NAMES = {
    "route",
    "api_route",
    "websocket",
    "command",
    "group",
    "fixture",
    "hookimpl",
    "register",
    "task",
    "shared_task",
    "receiver",
    "listens_for",
    "get",
    "post",
    "put",
    "delete",
    "head",
    "options",
    "callback",
    "listener",
    "handler",
    "errorhandler",
    "exception_handler",
    "middleware",
    "on_event",
    "validator",
    "field_validator",
    "model_validator",
    "root_validator",
}
# x.y decorators that wrap or describe the function but register nothing
NOT_REGISTRY = {
    "setter",
    "getter",
    "deleter",
    "wraps",
    "cache",
    "lru_cache",
    "cached_property",
    "cached",
    "memoize",
}
ASSIGN = (ast.Assign, ast.AnnAssign, ast.AugAssign)
LOOKUPS = {"import_module", "__import__", "getattr", "hasattr"}  # their strings get own evidence


def resolve_dynamic_refs(graph: CodeGraph) -> dict[str, list[str]]:
    """Per unit key, the evidence for each way something reaches the unit by name."""
    resolver = _Resolver(graph)
    resolver.packaging()
    resolver.config_files()
    for mod in graph.modules.values():
        if mod.tree is not None:
            resolver.python_module(mod)
    resolver.subclass_discovery()
    resolver.framework_bases()
    return dict(resolver.refs)


class _Resolver:
    def __init__(self, graph: CodeGraph):
        self.g = graph
        self.root = Path(graph.repo_dir)
        self.by_name = {m.name: m for m in graph.modules.values()}
        self.dotted = dict(self.by_name)  # module names, plus src-layout import names
        for mod in graph.modules.values():
            self.dotted.setdefault(import_name(mod.path), mod)
        self.methods: dict[str, list[str]] = defaultdict(list)
        for key, unit in graph._units.items():
            if unit.kind == "function" and "." in (unit.name or ""):
                self.methods[unit.name.split(".")[-1]].append(key)
        self.refs: dict[str, list[str]] = defaultdict(list)
        self.explained: set[tuple[str, str]] = set()  # (unit key, file) with a specific reason
        self.discovers: dict[str, list[str]] = defaultdict(list)  # class -> __subclasses__ sites

    def add(self, key: str | None, evidence: str, file: str | None = None) -> None:
        if key is None or key not in self.g._units or evidence in self.refs[key]:
            return
        self.refs[key].append(evidence)
        if file is not None:
            self.explained.add((key, file))

    def resolve(self, dotted: str, attr: str | None = None, depth: int = 0) -> str | None:
        """The unit a dotted name ("pkg.mod.func") or a "module:attr" pair names, or None."""
        if attr is not None:
            mod = self.dotted.get(dotted)
            return self._inside(mod, attr.split("."), depth) if mod else None
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            mod = self.dotted.get(".".join(parts[:i]))
            if mod is not None:
                return self._inside(mod, parts[i:], depth)
        return None

    def _inside(self, mod: _Module, rest: list[str], depth: int) -> str | None:
        if not rest:
            return mod.path
        qual = ".".join(rest)
        if qual in mod.defs:
            return f"{mod.path}::{qual}"
        alias = mod.aliases.get(rest[0])
        if alias is None or depth >= 3:  # re-exported from another module, a few hops at most
            return None
        target = alias[1] if alias[0] == "module" else f"{alias[1]}.{alias[2]}"
        return self.resolve(".".join([target, *rest[1:]]), depth=depth + 1)

    def entry_point(self, group: str, name: str, spec: str, file: str) -> None:
        spec = re.sub(r"\[.*\]\s*$", "", str(spec)).strip()  # extras: "pkg.cli:main [color]"
        module, _, attr = spec.partition(":")
        key = self.resolve(module.strip(), attr.strip() or None)
        self.add(key, f'entry point {group} "{name} = {spec}" in {file}', file)

    def packaging(self) -> None:
        """Entry points and build hooks in pyproject.toml, setup.cfg and setup.py."""
        data = _toml(self.root / "pyproject.toml")
        project, poetry = _table(data, "project"), _table(data, "tool", "poetry")
        groups = {
            "console_scripts": project.get("scripts"),
            "gui_scripts": project.get("gui-scripts"),
            "poetry scripts": poetry.get("scripts"),
        }
        for prefix, tables in (
            ("", project.get("entry-points")),
            ("poetry ", poetry.get("plugins")),
        ):
            if isinstance(tables, dict):
                groups.update({prefix + g: t for g, t in tables.items()})
        for group, table in groups.items():
            for name, spec in (table if isinstance(table, dict) else {}).items():
                if isinstance(spec, dict):  # poetry: {callable = "pkg:main"} or {reference = ...}
                    spec = spec.get("callable") or spec.get("reference") or ""
                self.entry_point(group, name, spec, "pyproject.toml")
        self._build_backend(_table(data, "build-system"))
        self._hatch_hooks(_table(data, "tool", "hatch"), "tool.hatch")
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(self.root / "setup.cfg", encoding="utf-8")
        except (configparser.Error, UnicodeDecodeError):
            parser = configparser.ConfigParser()
        if parser.has_section("options.entry_points"):
            for group, text in parser.items("options.entry_points"):
                self._entry_lines(group, text, "setup.cfg")
        setup = self.g.modules.get("setup.py")
        if setup is not None and setup.tree is not None:
            self._setup_py(setup.tree)

    def _entry_lines(self, group: str, text: str, file: str) -> None:
        for line in text.splitlines():
            if line.strip().startswith("["):
                group = line.strip().strip("[]")
            elif "=" in line:
                name, _, spec = line.partition("=")
                self.entry_point(group, name.strip(), spec, file)

    def _setup_py(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node) == "setup"):
                continue
            for kw in node.keywords:
                if kw.arg != "entry_points":
                    continue
                try:
                    value = ast.literal_eval(kw.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(value, str):
                    self._entry_lines("", value, "setup.py")
                for group, specs in value.items() if isinstance(value, dict) else ():
                    specs = [specs] if isinstance(specs, str) else specs
                    for spec in specs if isinstance(specs, list | tuple) else ():
                        self._entry_lines(group, str(spec), "setup.py")

    def _build_backend(self, build: dict) -> None:
        """An in-tree PEP 517 backend: the build frontend calls its hooks by name."""
        backend, paths = build.get("build-backend"), build.get("backend-path")
        if not isinstance(backend, str) or not isinstance(paths, list):
            return
        rel = backend.partition(":")[0].replace(".", "/")
        for folder in paths:
            for path in (f"{folder}/{rel}.py", f"{folder}/{rel}/__init__.py"):
                mod = self.g.modules.get(Path(path).as_posix().removeprefix("./"))
                if mod is None:
                    continue
                why = f'in-tree build backend "{backend}" in pyproject.toml'
                self.add(mod.path, why, "pyproject.toml")
                for hook in sorted(PEP517_HOOKS & set(mod.defs)):
                    self.add(f"{mod.path}::{hook}", f"PEP 517 build hook of the {why}")

    def _hatch_hooks(self, table: dict, where: str) -> None:
        """hatchling custom hooks: [tool.hatch.build.hooks.custom], metadata and target hooks."""
        for key, value in table.items() if isinstance(table, dict) else ():
            if key == "custom" and where.endswith(".hooks") and isinstance(value, dict):
                path = Path(str(value.get("path", "hatch_build.py"))).as_posix()
                why = f"hatchling custom hook file named in pyproject.toml [{where}.custom]"
                self.add(path, why, "pyproject.toml")
            elif isinstance(value, dict):
                self._hatch_hooks(value, f"{where}.{key}")

    def config_files(self) -> None:
        """Dotted names and module:attr strings in toml, yaml, json, ini and cfg files."""
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                path = Path(folder) / name
                if path.suffix not in CONFIG_SUFFIXES:
                    continue
                rel = path.relative_to(self.root).as_posix()
                try:
                    if path.stat().st_size > MAX_CONFIG_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for n, line in enumerate(text.splitlines(), 1):
                    for m in TOKEN.finditer(line):
                        if "." not in m.group(0) and ":" not in m.group(0):
                            continue  # a bare word names nothing for sure
                        key = self.resolve(m.group(1), m.group(2))
                        if key is not None and (key, rel) not in self.explained:
                            self.add(key, f'"{m.group(0)}" named in {rel}:{n}')

    def python_module(self, mod: _Module) -> None:
        self._settings_and_strings(mod)
        self._all(mod)
        for qual, node in mod.defs.items():
            for dec in getattr(node, "decorator_list", []):
                if self.registers(mod, dec):
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    self.add(f"{mod.path}::{qual}", f"registered by @{ast.unparse(target)}")
            if "." not in qual and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if system := module_hook(qual):
                    self.add(f"{mod.path}::{qual}", f"{system} hook: {system} calls it by name")
        modules = self._module_vars(mod)
        for cls, node in _calls(mod.tree):
            self._lookup(mod, cls, node, modules)

    def _settings_and_strings(self, mod: _Module) -> None:
        """Dotted strings in .py files; under an UPPER_CASE setting (INSTALLED_APPS, MIDDLEWARE)
        the evidence names the setting."""
        settings: dict[int, str] = {}
        skip = {
            id(arg)
            for call in ast.walk(mod.tree)
            if isinstance(call, ast.Call) and _call_name(call) in LOOKUPS
            for arg in call.args
        }
        for stmt in mod.tree.body:
            if not isinstance(stmt, ASSIGN) or stmt.value is None:
                continue
            for t in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                if isinstance(t, ast.Name) and t.id.isupper():
                    settings.update({id(s): t.id for s in ast.walk(stmt.value)})
        for node in ast.walk(mod.tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in skip:
                continue
            m = FULL.fullmatch(node.value)
            if m is None or ("." not in node.value and ":" not in node.value):
                continue
            key = self.resolve(m.group(1), m.group(2))
            if key is None or key == mod.path:  # a module naming itself (a logger) says nothing
                continue
            if id(node) in settings:
                self.add(key, f'"{node.value}" named in {mod.path} {settings[id(node)]}')
            else:
                self.add(key, f'"{node.value}" named in a string in {mod.path}:{node.lineno}')

    def _all(self, mod: _Module) -> None:
        for stmt in mod.tree.body:
            if not isinstance(stmt, ASSIGN) or stmt.value is None:
                continue
            target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
            if not (isinstance(target, ast.Name) and target.id == "__all__"):
                continue
            for elt in getattr(stmt.value, "elts", []):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    key = self._inside(mod, [elt.value], 0)
                    self.add(key, f"listed in __all__ of {mod.path}")

    def _module_vars(self, mod: _Module) -> dict[str, str]:
        """Names bound to import_module("literal") or __import__("literal"): name -> module."""
        found = {}
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                module = self._imported(mod, node.value)
                for t in node.targets:
                    if isinstance(t, ast.Name) and module:
                        found[t.id] = module
        return found

    def _imported(self, mod: _Module, call: ast.Call) -> str | None:
        """The module key import_module or __import__ loads with a literal name, or None."""
        if _call_name(call) not in ("import_module", "__import__") or not call.args:
            return None
        name = call.args[0]
        if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            return None
        dotted = name.value
        if dotted.startswith("."):  # relative to package=..., __package__ or __name__
            level = len(dotted) - len(dotted.lstrip("."))
            anchor = call.args[1] if len(call.args) > 1 else None
            anchor = next((k.value for k in call.keywords if k.arg == "package"), anchor)
            if isinstance(anchor, ast.Constant) and isinstance(anchor.value, str):
                package = anchor.value.split(".")
            elif isinstance(anchor, ast.Name) and anchor.id == "__name__":
                package = mod.name.split(".")
            elif isinstance(anchor, ast.Name) and anchor.id == "__package__":
                is_pkg = mod.path.endswith("__init__.py")
                package = mod.name.split(".") if is_pkg else mod.name.split(".")[:-1]
            else:
                return None
            base = package[: len(package) - (level - 1)] if level > 1 else package
            dotted = ".".join([*base, dotted.lstrip(".")]).strip(".")
        mod_key = self.resolve(dotted)
        return mod_key if mod_key in self.g.modules else None

    def _lookup(self, mod: _Module, cls: str | None, call: ast.Call, modules: dict) -> None:
        """getattr/hasattr with a literal (or literal-prefixed) name, import_module, and
        X.__subclasses__()."""
        where = f"{mod.path}:{call.lineno}"
        name = _call_name(call)
        if module := self._imported(mod, call):
            self.add(module, f"{name}({ast.unparse(call.args[0])}) in {where}")
        if name == "__subclasses__" and isinstance(call.func, ast.Attribute):
            owner = self._scope(mod, cls, call.func.value, modules)
            if owner is not None and owner[1] is not None:
                self.discovers[owner[1]].append(where)
            return
        if name not in ("getattr", "hasattr") or len(call.args) < 2:
            return
        attr, prefix = _literal(call.args[1])
        if attr is None and prefix is None:
            return
        text = f"{name}({ast.unparse(call.args[0])}, {ast.unparse(call.args[1])}) in {where}"
        owner = self._scope(mod, cls, call.args[0], modules)
        if owner is None:
            if attr is not None:  # unknown object: every method with this name, like obj.attr
                for key in self.methods.get(attr, ()):
                    self.add(key, text)
            return
        target, qual = owner
        if target is not None:
            for key in self._members(target, qual, attr, prefix):
                self.add(key, text)

    def _scope(self, mod: _Module, cls: str | None, expr: ast.AST, modules: dict):
        """What an expression stands for: (module, None), (module, unit key) for a class or
        function in it, (None, None) for a library name, or None when it is unknown."""
        if isinstance(expr, ast.Name) and expr.id in ("self", "cls") and cls:
            return mod, f"{mod.path}::{cls}"
        if isinstance(expr, ast.Call) and _call_name(expr) == "type" and cls:  # type(self)
            return mod, f"{mod.path}::{cls}"
        if not isinstance(expr, ast.Name):
            return None
        if expr.id in modules:
            return self.g.modules[modules[expr.id]], None
        if expr.id in mod.defs:
            return mod, f"{mod.path}::{expr.id}"
        alias = mod.aliases.get(expr.id)
        if alias is None:
            return None
        key = self.resolve(alias[1] if alias[0] == "module" else f"{alias[1]}.{alias[2]}")
        if key is None:
            return None, None
        path, _, qual = key.partition("::")
        return self.g.modules[path], (key if qual else None)

    def _members(self, mod: _Module, cls_key: str | None, attr, prefix) -> list[str]:
        """Units of a module (or of one class in it) named attr, or starting with prefix."""
        head = cls_key.split("::")[1] + "." if cls_key else ""
        found = []
        for qual in mod.defs:
            if not qual.startswith(head) or "." in qual[len(head) :]:
                continue
            short = qual[len(head) :]
            if short == attr or (prefix and short.startswith(prefix)):
                found.append(f"{mod.path}::{qual}")
        return found

    def registers(self, mod: _Module, dec: ast.AST) -> bool:
        """A decorator that registers the function by name: @app.route(...), @router.get,
        @click.command(), @pytest.fixture, @receiver(...), @registry.register, ..."""
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            return target.id in REGISTRY_NAMES
        if not isinstance(target, ast.Attribute) or target.attr in NOT_REGISTRY:
            return False
        if target.attr in REGISTRY_NAMES:
            return True
        # any other x.y registers when x is an object of the project (app, router, registry),
        # not a module or a library name (functools.wraps, pytest.mark.slow)
        head = ast.unparse(target.value).split(".")[0]
        alias = mod.aliases.get(head)
        if alias is None:
            return head not in ("self", "cls")
        return alias[0] == "name" and alias[1] in self.dotted

    def _bases(self) -> dict[str, set[str]]:
        """Project class -> its direct subclasses in the project."""
        children: dict[str, set[str]] = defaultdict(set)
        for mod in self.g.modules.values():
            for qual, node in mod.defs.items():
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    base = base.value if isinstance(base, ast.Subscript) else base
                    if not isinstance(base, ast.Name | ast.Attribute):
                        continue
                    head, *rest = ast.unparse(base).split(".")
                    if head in mod.defs and not rest:
                        key = f"{mod.path}::{head}"
                    elif alias := mod.aliases.get(head):
                        target = alias[1] if alias[0] == "module" else f"{alias[1]}.{alias[2]}"
                        key = self.resolve(".".join([target, *rest]))
                    else:
                        continue
                    if key and "::" in key:
                        children[key].add(f"{mod.path}::{qual}")
        return children

    def subclass_discovery(self) -> None:
        """Subclasses (direct or not) of a class whose __subclasses__() something enumerates."""
        if not self.discovers:
            return
        children = self._bases()
        for base, sites in self.discovers.items():
            short = base.split("::")[1]
            queue, seen = deque(children.get(base, ())), set()
            while queue:
                key = queue.popleft()
                if key in seen:
                    continue
                seen.add(key)
                queue.extend(children.get(key, ()))
                why = f"subclass of {short}, which {sites[0]} discovers via __subclasses__()"
                self.add(key, why)

    def framework_bases(self) -> None:
        """Classes a framework finds by their base class (DISCOVERED_BASES)."""
        for mod in self.g.modules.values():
            for qual, node in mod.defs.items():
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in external_bases(mod, qual, self.by_name, set()):
                    if what := discovered_base(base):
                        why = f"{what} class (framework base class {base})"
                        self.add(f"{mod.path}::{qual}", why)
                        break


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _table(data: dict, *keys: str) -> dict:
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else {}


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _literal(arg: ast.AST) -> tuple[str | None, str | None]:
    """(name, None) for a literal string, (None, prefix) for f"prefix{...}" or "prefix" + x."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value, None
    first = None
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
    elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        first = arg.left
    if isinstance(first, ast.Constant) and isinstance(first.value, str) and len(first.value) >= 2:
        return None, first.value
    return None, None


def _calls(tree: ast.Module):
    """Every call in a module, with the top-level class it is inside (or None)."""
    for stmt in tree.body:
        cls = stmt.name if isinstance(stmt, ast.ClassDef) else None
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                yield cls, node
