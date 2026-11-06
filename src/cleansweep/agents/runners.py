"""How a project runs its tests, read from its own config: pytest settings, tox, nox, a Makefile
`test` target, or the test files themselves (unittest only, or pytest style).

detect() returns {"runner", "command", "source"} plus what the workspace needs to run it:
"paths" for pytest, "start"/"top"/"pattern" for unittest, "argv" for a plain command (its exit
code is the only result). tox, nox and make are not run themselves: the pytest or unittest
command they run is, with its test paths; a Makefile target that runs neither is run as is."""

from __future__ import annotations

import ast
import configparser
import re
import shlex
import tomllib
from pathlib import Path

from cleansweep.analysis.graph import iter_py_files

PYTEST_FILES = (
    ("pytest.ini", None),
    ("pyproject.toml", "[tool.pytest.ini_options]"),
    ("setup.cfg", "[tool:pytest]"),
    ("tox.ini", "[pytest]"),
)
WRAPPERS = (["poetry", "run"], ["uv", "run"], ["pipenv", "run"], ["hatch", "run"], ["pdm", "run"])
MAKE_VAR = re.compile(r"\$[({][A-Za-z_]+[)}]")


def detect(root: str | Path) -> dict:
    """The project's test command and where it came from."""
    root = Path(root)
    for name, marker in PYTEST_FILES:
        path = root / name
        if path.is_file() and (marker is None or marker in _read(path)):
            return _pytest([], f"pytest settings in {name}")
    for source, line in _tox(root) + _nox(root) + _make(root):
        found = runner_of(line, root)
        if found:
            return {**found, "source": f"{source} runs `{line.strip()}`"}
    if any(root.rglob("conftest.py")):
        return _pytest([], "conftest.py")
    files = [p for p in iter_py_files(root) if _named_like_a_test(p)]
    styles = {p: _style(root / p) for p in files}
    used = [p for p, s in styles.items() if s]
    if used and all(styles[p] == "unittest" for p in used):
        return _unittest(root, used, "test files that are all unittest.TestCase")
    if _make(root):
        return {
            "runner": "command",
            "command": "make test",
            "argv": ["make", "test"],
            "source": "the Makefile's test target (its exit code is the only result)",
        }
    if used:
        return _pytest([], "test files in pytest style")
    return {"runner": "none", "command": "none (no test files)", "source": "no test files found"}


def runner_of(line: str, root: Path) -> dict | None:
    """The pytest or unittest command in one command line, e.g. tox's `coverage run -m pytest
    {posargs} tests`, or None when it runs neither."""
    try:
        words = shlex.split(MAKE_VAR.sub("python", line.strip().lstrip("@-")))
    except ValueError:
        return None
    while words and "=" in words[0] and not words[0].startswith("-"):
        words = words[1:]  # VAR=value prefixes
    for wrapper in WRAPPERS:
        if words[: len(wrapper)] == wrapper:
            words = words[len(wrapper) :]
    if words[:2] == ["coverage", "run"]:
        words = words[2:]
        while words and words[0].startswith("-") and words[0] != "-m":
            words = words[1:]
        words = words[1:] if words[:1] == ["-m"] else words
    elif len(words) > 1 and "python" in words[0] and words[1] == "-m":
        words = words[2:]
    if not words:
        return None
    if words[0] in ("pytest", "py.test"):
        paths = [w for w in (_plain(a) for a in words[1:]) if w and (root / w).exists()]
        return _pytest(paths, "")
    if words[0] == "unittest":
        return _unittest_args(root, words[1:])
    return None


def _pytest(paths: list[str], source: str) -> dict:
    command = " ".join(["pytest", *paths])
    return {"runner": "pytest", "command": command, "paths": paths, "source": source}


def _unittest(root: Path, files: list[str], source: str) -> dict:
    folders = {Path(p).parent for p in files}
    start = Path(*_common([f.parts for f in folders])) if folders else Path(".")
    pattern = "test*.py" if all(Path(p).name.startswith("test") for p in files) else "*test*.py"
    return {**_unittest_spec(root, start.as_posix() or ".", pattern), "source": source}


def _unittest_args(root: Path, args: list[str]) -> dict:
    """`unittest discover -s tests -p "test_*.py"`; any other form discovers from the root."""
    opts = {"start": ".", "pattern": "test*.py", "top": None}
    flags = {"-s": "start", "-p": "pattern", "-t": "top"}
    rest, positional = list(args[1:]) if args[:1] == ["discover"] else [], []
    while rest:
        word = rest.pop(0)
        if word in flags and rest:
            opts[flags[word]] = rest.pop(0)
        elif not word.startswith("-"):
            positional.append(word)
    opts.update(zip(("start", "pattern", "top"), positional, strict=False))
    start = _plain(opts["start"]) or "."
    return {**_unittest_spec(root, start, opts["pattern"], opts["top"]), "source": ""}


def _unittest_spec(root: Path, start: str, pattern: str, top: str | None = None) -> dict:
    # discovery imports the start folder as a package from the top folder when it is one
    if top is None:
        top = "." if start == "." or (root / start / "__init__.py").exists() else start
    command = f"python -m unittest discover -s {start} -t {top} -p '{pattern}'"
    return {
        "runner": "unittest",
        "command": command,
        "start": start,
        "top": top,
        "pattern": pattern,
    }


def _plain(arg: str) -> str | None:
    """A path argument without tox substitutions, or None for an option or a placeholder."""
    if arg.startswith("-"):
        return None
    arg = re.sub(r"^\{toxinidir\}/?", "", arg)
    return None if "{" in arg or "$" in arg else arg.rstrip("/") or "."


def _common(parts: list[tuple]) -> tuple:
    first = parts[0]
    n = 0
    while n < len(first) and all(len(p) > n and p[n] == first[n] for p in parts):
        n += 1
    return first[:n]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tox(root: Path) -> list[tuple[str, str]]:
    """(source, command line) for each tox test environment command."""
    out: list[tuple[str, str]] = []
    texts = [("tox.ini", _read(root / "tox.ini"))]
    try:
        data = tomllib.loads(_read(root / "pyproject.toml"))
    except tomllib.TOMLDecodeError:
        data = {}
    tox = data.get("tool", {}).get("tox", {})
    texts.append(("pyproject.toml [tool.tox]", tox.get("legacy_tox_ini", "")))
    for name, text in texts:
        if not text:
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(text)
        except configparser.Error:
            continue
        for section in parser.sections():
            if section.startswith("testenv") and parser.has_option(section, "commands"):
                lines = parser.get(section, "commands").replace("\\\n", " ").splitlines()
                out += [(f"{name} [{section}]", ln) for ln in lines if ln.strip()]
    for env in [tox.get("env_run_base", {}), *tox.get("env", {}).values()]:
        for cmd in env.get("commands", []) if isinstance(env, dict) else []:
            if isinstance(cmd, list) and all(isinstance(w, str) for w in cmd):
                out.append(("pyproject.toml [tool.tox]", shlex.join(cmd)))
    return out


def _nox(root: Path) -> list[tuple[str, str]]:
    """(source, command line) for each session.run(...) in noxfile.py, test sessions first."""
    try:
        tree = ast.parse(_read(root / "noxfile.py"))
    except SyntaxError:
        return []
    found = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
            ):
                words = [a.value for a in node.args if isinstance(a, ast.Constant)]
                if words and all(isinstance(w, str) for w in words):
                    found.append((("test" not in fn.name), f"noxfile.py session {fn.name}", words))
    found.sort(key=lambda f: f[0])
    return [(source, shlex.join(words)) for _, source, words in found]


def _make(root: Path) -> list[tuple[str, str]]:
    """(source, recipe line) for the Makefile's `test` target."""
    lines = _read(root / "Makefile").splitlines()
    out, inside = [], False
    for line in lines:
        if re.match(r"^test\s*:", line):
            inside = True
        elif inside and line.startswith("\t"):
            out.append(("the Makefile's test target", line.strip()))
        elif inside and line.strip():
            break
    return out or ([("the Makefile's test target", "make test")] if inside else [])


def _named_like_a_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test") or name.endswith(("_test.py", "_tests.py"))


def _style(path: Path) -> str | None:
    """ "unittest" (TestCase classes only), "pytest" (pytest imports or bare test functions),
    or None when the file holds no tests."""
    try:
        tree = ast.parse(_read(path))
    except (SyntaxError, ValueError):
        return None
    cases = pytest_style = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            pytest_style |= any(n.split(".")[0] == "pytest" for n in names)
        elif isinstance(node, ast.ClassDef):
            cases |= any(ast.unparse(b).endswith("TestCase") for b in node.bases)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            pytest_style = True
    return "pytest" if pytest_style else "unittest" if cases else None
