"""The project's own test environment: a venv with the project installed, so the tests
exercise the cleaned copy and not an installed original.

With a src layout the copy's src/ goes first on PYTHONPATH. The install plan comes from the
project's files: pip for pyproject.toml (with its test/dev extras and dependency groups),
setup.py or setup.cfg, and requirements*.txt; poetry or uv when the project has their lock file
and the tool is installed, with pip reading pyproject.toml as the fallback. The venv lives in
the run's output folder (outside the workspace) and can fall back on this interpreter's packages
(pytest, coverage). If the install fails, the tests run with CleanSweep's interpreter and the
report says so."""

from __future__ import annotations

import ast
import configparser
import os
import shlex
import shutil
import sys
import sysconfig
import tomllib
from collections.abc import Callable
from pathlib import Path

VENV = ".cs_venv"
INSTALL_TIMEOUT = 900
WANTED = ("test", "tests", "testing", "dev", "develop")
NOTHING = "none needed (no packaging or requirements files)"


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _setup_extras(root: Path) -> list[str]:
    """Extras named in setup.cfg [options.extras_require] or a literal extras_require= dict."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(root / "setup.cfg", encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        pass
    if parser.has_section("options.extras_require"):
        return list(parser["options.extras_require"])
    try:
        tree = ast.parse((root / "setup.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return []
    values = {
        t.id: n.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    for node in ast.walk(tree):
        for kw in getattr(node, "keywords", []) if isinstance(node, ast.Call) else []:
            value = values.get(kw.value.id) if isinstance(kw.value, ast.Name) else kw.value
            if kw.arg == "extras_require" and isinstance(value, ast.Dict):
                return [k.value for k in value.keys if isinstance(k, ast.Constant)]
    return []


def _group(groups: dict, name: str, seen: set) -> list[str]:
    """A PEP 735 dependency group's requirements, with included groups expanded."""
    out = []
    for entry in groups.get(name, []):
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and entry.get("include-group") not in seen:
            seen.add(entry["include-group"])
            out += _group(groups, entry["include-group"], seen)
    return out


def _poetry_dev(poetry: dict) -> list[str]:
    """Package names of poetry's test/dev groups (versions dropped: pip reads no ^ ranges)."""
    tables = [poetry.get("dev-dependencies", {})]
    tables += [g.get("dependencies", {}) for n, g in poetry.get("group", {}).items() if n in WANTED]
    return sorted({name for t in tables for name in t if name != "python"})


def _requirements(root: Path, packaged: bool) -> list[str]:
    """Requirement files to install: requirements.txt and the dev/test ones (every
    requirements*.txt for a project with no packaging and no such file)."""
    found = sorted(p.name for p in root.glob("requirements*.txt"))
    found += sorted(f"requirements/{p.name}" for p in root.glob("requirements/*.txt"))
    wanted = [
        f
        for f in found
        if Path(f).name == "requirements.txt" or any(w in Path(f).name for w in ("dev", "test"))
    ]
    return wanted or ([] if packaged else found)


def install_plan(root: str | Path, which: Callable[[str], str | None] = shutil.which) -> dict:
    """How to install the project for its tests: {"tool", "steps", "fallback", "source"}.

    Each step is an argument list: "pip ..." runs as `<python> -m pip ...`; "poetry install" and
    "uv sync" run the tool (used only when its lock file exists and `which` finds it; the
    fallback then installs with pip). Pass which=lambda _: None for a pip-only environment."""
    root = Path(root)
    data = _toml(root / "pyproject.toml")
    project, tool = data.get("project", {}), data.get("tool", {})
    packaged = bool(project or tool.get("poetry") or data.get("build-system"))
    packaged |= (root / "setup.py").exists() or (root / "setup.cfg").exists()
    extras = [*project.get("optional-dependencies", {}), *_setup_extras(root)]
    extras = sorted({e for e in extras if e in WANTED})
    groups = data.get("dependency-groups", {})
    pip: list[list[str]] = []
    if packaged:
        pip.append(["pip", "install", "-e", f".[{','.join(extras)}]" if extras else "."])
    dev = [r for g in groups if g in WANTED for r in _group(groups, g, {g})]
    dev += _poetry_dev(tool.get("poetry", {}))
    if dev:
        pip.append(["pip", "install", *dict.fromkeys(dev)])
    pip += [["pip", "install", "-r", f] for f in _requirements(root, packaged)]
    files = [f for f in ("pyproject.toml", "setup.py", "setup.cfg") if (root / f).exists()]
    source = ", ".join(files + [s[-1] for s in pip if s[2] == "-r"]) or "no packaging files"
    plan = {"tool": "pip", "steps": pip, "fallback": [], "source": source}
    if extras and pip:
        plan["fallback"] = [["pip", "install", "-e", "."], *pip[1:]]
    if tool.get("poetry") and (root / "poetry.lock").exists() and which("poetry"):
        names = [g for g in tool["poetry"].get("group", {}) if g in WANTED]
        step = ["poetry", "install", "--no-interaction"]
        step += ["--with", ",".join(names)] if names else []
        plan.update(tool="poetry", steps=[step], fallback=pip, source="poetry.lock")
    elif (root / "uv.lock").exists() and which("uv"):
        flags = [w for g in groups if g in WANTED for w in ("--group", g)]
        flags += [w for e in extras for w in ("--extra", e)]
        plan.update(tool="uv", steps=[["uv", "sync", "--frozen", *flags]], fallback=pip)
        plan["source"] = "uv.lock"
    return plan


def describe(plan: dict) -> str:
    """The plan as one line for the brief, e.g. "pip install -e .[test] && pip install -r
    requirements-dev.txt"."""
    text = " && ".join(shlex.join(s) for s in plan["steps"]) or NOTHING
    if plan["fallback"] and plan["tool"] != "pip":
        text += f" (else {' && '.join(shlex.join(s) for s in plan['fallback'])})"
    return text


def pip_commands(install: str) -> list[list[str]]:
    """The `pip install ...` parts of an install command, as pip argument lists."""
    out = []
    for part in install.split("&&"):
        words = shlex.split(part.strip())
        if words[:2] == ["pip", "install"] and len(words) > 2:
            out.append(words[2:])
    return out


def _see_host_packages(ws, python: Path) -> None:
    """Let the venv fall back on this interpreter's packages (pytest, coverage): a venv made from
    a venv only sees the base interpreter's. The project's own install comes first; plain paths
    added this way don't run their .pth hooks, so an installed original stays invisible."""
    code, out = ws.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]
    )
    if code != 0:
        return
    paths = sorted({sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]})
    (Path(out.strip().splitlines()[-1]) / "_cleansweep_host.pth").write_text(
        "\n".join(paths) + "\n"
    )


def src_path(root: Path) -> Path | None:
    """The src/ folder of a src layout: it holds a package or a module."""
    src = root / "src"
    if not src.is_dir():
        return None
    found = any(p.suffix == ".py" or (p.is_dir() and any(p.glob("*.py"))) for p in src.iterdir())
    return src if found else None


def _argv(step: list[str], python: Path) -> list[str]:
    if step[0] == "pip":
        return [str(python), "-m", "pip", "install", "-q", *step[2:]]
    return step


def _run_steps(rt, steps: list[list[str]], python: Path, venv: Path) -> str | None:
    """Run install steps in order; the first failure as a short line, or None."""
    ws = rt.ws
    tool_env = {  # poetry and uv install into the active venv
        "VIRTUAL_ENV": str(venv),
        "UV_PROJECT_ENVIRONMENT": str(venv),
        "PATH": f"{venv / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    for step in steps:
        saved = ws.extra_env
        ws.extra_env = {**saved, **(tool_env if step[0] != "pip" else {})}
        try:
            code, out = ws.run(_argv(step, python), timeout=INSTALL_TIMEOUT)
        finally:
            ws.extra_env = saved
        if code != 0:
            last = out.strip().splitlines()[-1][:200] if out.strip() else f"exit {code}"
            return f"{shlex.join(step)}: {last}"
    return None


def prepare(rt) -> dict:
    """Set the workspace's interpreter and environment for the project's tests."""
    ws, root = rt.ws, Path(rt.ws.path)
    info: dict = {"python": ws.python, "install": "not needed"}
    src = src_path(root)
    if src is not None:
        old = ws.extra_env.get("PYTHONPATH") or os.environ.get("PYTHONPATH", "")
        ws.extra_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(src), old]))
        info["pythonpath"] = "src"
    setting = rt.acfg.get("install", "auto")
    if ws.python != sys.executable:
        own = getattr(ws, "install_info", "") or "the workspace's own environment (its container)"
        return {**info, "install": own}
    plan = (rt.brief or {}).get("install_plan")
    if plan is None:  # a brief written without the plan: its pip commands
        commands = pip_commands((rt.brief or {}).get("install_command", ""))
        plan = {"tool": "pip", "steps": [["pip", "install", *c] for c in commands]}
    if setting == "off" or not plan["steps"]:
        return info
    venv = rt.out / VENV  # outside the workspace, so no detector or diff ever sees it
    python = venv / "bin" / "python"
    rt.log.emit(
        "tool_call",
        agent="tester",
        payload={"tool": "install", "args": {"commands": [shlex.join(s) for s in plan["steps"]]}},
    )
    code, out = ws.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)], timeout=INSTALL_TIMEOUT
    )
    failed = f"python -m venv: {out.strip()[-200:]}" if code != 0 else None
    if failed is None:
        _see_host_packages(ws, python)
        failed = _run_steps(rt, plan["steps"], python, venv)
        if failed and plan.get("fallback"):
            failed = _run_steps(rt, plan["fallback"], python, venv) and failed
            info["fallback"] = failed is None
    if failed:
        info["install"] = f"failed ({failed})"
    else:
        ws.python = str(python)
        how = f"{plan['tool']}, " if plan.get("tool", "pip") != "pip" else ""
        how = "pip (fallback), " if info.get("fallback") else how
        info.update(
            python=str(python), install=f"installed into {VENV} ({how}next to the workspace)"
        )
    rt.log.emit(
        "tool_result", agent="tester", payload={"tool": "install", "result": info["install"]}
    )
    return info
