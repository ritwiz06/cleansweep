"""Explorer: builds the project brief (languages, frameworks, entry points, how to install and
test, CI and config files) and runs the secret scan's report."""

from __future__ import annotations

import ast
import re
import tomllib
from collections import Counter
from pathlib import Path

from cleansweep.analysis.frameworks import FRAMEWORKS
from cleansweep.analysis.graph import is_test_file, iter_py_files

from .protocol import load_prompt, react
from .secrets import is_secret_file, public_findings
from .tools import Tool, ToolSet, read_code

NAME = "explorer"
OTHER_FRAMEWORKS = (
    "flask",
    "fastapi",
    "streamlit",
    "click",
    "typer",
    "pydantic",
    "sqlalchemy",
    "numpy",
    "pandas",
    "torch",
)
UI_FRAMEWORKS = ("textual", "streamlit", "tkinter", "PyQt5", "PySide6", "kivy", "gradio")
CI_FILES = (
    ".github/workflows",
    ".gitlab-ci.yml",
    "tox.ini",
    "noxfile.py",
    ".pre-commit-config.yaml",
    "Makefile",
    "azure-pipelines.yml",
)
CONFIG_FILES = (
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements.txt",
    "ruff.toml",
    "mypy.ini",
    "pytest.ini",
    "conftest.py",
)
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}
# where a project enforces its formatter: CI configs and pre-commit hooks
FORMATTER_FILES = (
    ".pre-commit-config.yaml",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
)
BLACK = r"(?:^|[\s\"'`;&|(/=])black(?:-pre-commit-mirror)?(?:[\s\"'`;&|)]|$)"
FORMATTERS = (
    ("ruff format", re.compile(r"\bruff[ -]format\b")),
    # "black" as a command, hook id or repository name, not "black-box" or "blacklist"
    ("black", re.compile(BLACK, re.M)),
)
FINAL_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def _imports(repo_dir: str, paths: list[str]) -> Counter:
    found: Counter = Counter()
    for rel in paths:
        try:
            tree = ast.parse((Path(repo_dir) / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found[node.module.split(".")[0]] += 1
    return found


def _pyproject(root: Path) -> dict:
    try:
        return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def install_command(root: Path, project: dict) -> str:
    """How to install the project for its tests, from its packaging files."""
    extras = project.get("optional-dependencies", {})
    test_extra = next((e for e in ("test", "tests", "dev", "testing") if e in extras), None)
    if project or (root / "setup.py").exists() or (root / "setup.cfg").exists():
        return f"pip install -e .[{test_extra}]" if test_extra else "pip install -e ."
    reqs = sorted(p.name for p in root.glob("requirements*.txt"))
    if reqs:
        return " && ".join(f"pip install -r {r}" for r in reqs)
    return "none needed (no packaging or requirements files)"


def enforced_formatter(root: Path) -> str | None:
    """The formatter the project's CI or pre-commit hooks run, e.g. "ruff format
    (.pre-commit-config.yaml)", or None when nothing enforces one."""
    for pattern in FORMATTER_FILES:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(errors="replace")
            for name, regex in FORMATTERS:
                if regex.search(text):
                    return f"{name} ({path.relative_to(root)})"
    return None


SHELL_END = re.compile(r"&&|\|\||[;|#]")


def formatter_paths(root: Path) -> list[str] | None:
    """The folders and files the enforced formatter runs on ("ruff format --check src/ tests/"
    gives ["src", "tests"]), or None when it covers the whole project (no paths, ".", or a
    pre-commit hook)."""
    found: set[str] = set()
    for pattern in FORMATTER_FILES:
        for path in sorted(root.glob(pattern)):
            for line in path.read_text(errors="replace").splitlines():
                for _, regex in FORMATTERS:
                    m = regex.search(line)
                    if not m:
                        continue
                    rest = SHELL_END.split(line[m.end() :], 1)[0]
                    args = [a.strip("\"'") for a in rest.split() if not a.startswith("-")]
                    args = [a.rstrip("/") for a in args if (root / a).exists()]
                    if not args or any(a in (".", "") for a in args):
                        return None
                    found.update(args)
    return sorted(found) or None


def project_facts(repo_dir: str, graph) -> dict:
    """The deterministic part of the brief."""
    root = Path(repo_dir)
    files = [
        p for p in root.rglob("*") if p.is_file() and not SKIP & set(p.relative_to(root).parts)
    ]
    languages = Counter(p.suffix.lstrip(".") or p.name for p in files)
    py = iter_py_files(repo_dir)
    imports = _imports(repo_dir, py)
    known = list(FRAMEWORKS) + list(OTHER_FRAMEWORKS)
    frameworks = [f for f in known if imports.get(f) or imports.get(f.lower())]
    pyproject = _pyproject(root)
    project = pyproject.get("project", {})
    scripts = sorted(project.get("scripts", {}))
    tests = [p for p in py if is_test_file(p)]
    return {
        "name": project.get("name") or root.name,
        "languages": dict(languages.most_common(6)),
        "python_files": len(py),
        "test_files": len(tests),
        "frameworks": frameworks,
        "ui_framework": next((f for f in UI_FRAMEWORKS if imports.get(f)), None),
        "entry_points": sorted(graph.entries)[:20] + [f"script: {s}" for s in scripts],
        "install_command": install_command(root, project),
        "test_command": "pytest",
        "ci_files": [c for c in CI_FILES if (root / c).exists()],
        "formatter": enforced_formatter(root),
        "formatter_paths": formatter_paths(root),
        "config_files": [c for c in CONFIG_FILES if (root / c).exists()],
        "dependencies": len(project.get("dependencies", [])),
    }


def _readme(root: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = root / name
        if path.is_file():
            paras = [p.strip() for p in path.read_text(errors="replace").split("\n\n") if p.strip()]
            text = next((p for p in paras if not p.startswith(("#", "!", "[", "<", "="))), "")
            return " ".join(text.split())[:400]
    return ""


def run(rt) -> None:
    """ONBOARD: write the brief, cache it and send it to the agents that use it."""
    budget = rt.budget(NAME)
    facts = project_facts(rt.ws.path, rt.graph)
    facts["name"] = (
        facts["name"] if facts["name"] != Path(rt.ws.path).name else rt.ws.repo_id.split(":", 1)[-1]
    )
    rt.log.emit("tool_result", agent=NAME, payload={"tool": "project_facts", "result": facts})
    summary = (
        _readme(Path(rt.ws.path)) or f"A Python project with {facts['python_files']} Python files."
    )
    notes: list[str] = []
    if rt.llm is not None and rt.ablation != "no_research":
        result = react(
            NAME,
            rt.llm,
            load_prompt(NAME),
            _task(facts, summary),
            _tools(rt),
            FINAL_SCHEMA,
            budget,
            rt.log,
        )
        if result.final:
            summary = result.final["summary"] or summary
            notes = result.final.get("notes", [])
    secrets = public_findings(rt.secrets)
    brief = {**facts, "summary": summary, "notes": notes, "secrets": secrets}
    rt.brief = brief
    art = rt.artifact("brief", brief)
    rt.board.post(
        "brief",
        NAME,
        {
            "summary": summary,
            "frameworks": facts["frameworks"],
            "test_command": facts["test_command"],
            "install_command": facts["install_command"],
            "entry_points": facts["entry_points"],
            "languages": facts["languages"],
            "ui_framework": facts["ui_framework"],
            "secret_files": len(secrets["files"]),
            "secret_findings": len(secrets["findings"]),
        },
        artifacts=[art],
    )
    rt.record_usage(NAME, budget)
    rt.log.v1(
        "open",
        {
            "repo_id": rt.ws.repo_id,
            "workspace": rt.ws.path,
            "llm": getattr(rt.llm, "model", None),
            "seconds": 0.0,
        },
    )
    rt.log.v1("analyze", {"units": len(rt.graph.units()), "seconds": 0.0})


def _task(facts: dict, summary: str) -> str:
    return (
        f"Project facts found by the tools:\n{facts}\n\nREADME start: {summary or '(none)'}\n\n"
        "Read what you need, then give a two- or three-sentence summary of what the project does "
        "and up to three notes that matter for cleaning it up safely."
    )


def _tools(rt) -> ToolSet:
    def list_files(pattern: str = "*") -> str:
        root = Path(rt.ws.path)
        found = sorted(
            p.relative_to(root).as_posix()
            for p in root.glob(pattern)
            if p.is_file() and not SKIP & set(p.relative_to(root).parts)
        )
        shown = [f"{f} [withheld]" if is_secret_file(f) else f for f in found[:60]]
        return f"{len(found)} files: {shown}"

    return ToolSet(
        [
            Tool(
                "list_files",
                "List files matching a glob pattern (e.g. *.toml, docs/*).",
                {"pattern": {"type": "string"}},
                [],
                list_files,
            ),
            Tool(
                "read_file",
                "Read lines of a file (at most 120).",
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                ["path", "start_line", "end_line"],
                lambda **a: read_code(rt, **a),
            ),
        ]
    )
