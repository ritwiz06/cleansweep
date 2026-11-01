"""The project's own test environment: a venv with the project installed, so the tests
exercise the cleaned copy and not an installed original.

With a src layout the copy's src/ goes first on PYTHONPATH. A project with packaging or
requirements files is installed into a venv in the run's output folder (outside the workspace),
which can fall back on this interpreter's packages (pytest, coverage). If the install fails,
the tests run with CleanSweep's interpreter and the report says so."""

from __future__ import annotations

import os
import shlex
import sys
import sysconfig
from pathlib import Path

VENV = ".cs_venv"
INSTALL_TIMEOUT = 900


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


def prepare(rt) -> dict:
    """Set the workspace's interpreter and environment for the project's tests."""
    ws, root = rt.ws, Path(rt.ws.path)
    info: dict = {"python": ws.python, "install": "not needed"}
    src = root / "src"
    if src.is_dir() and any(p.is_dir() and (p / "__init__.py").exists() for p in src.iterdir()):
        old = ws.extra_env.get("PYTHONPATH") or os.environ.get("PYTHONPATH", "")
        ws.extra_env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(src), old]))
        info["pythonpath"] = "src"
    setting = rt.acfg.get("install", "auto")
    commands = pip_commands((rt.brief or {}).get("install_command", ""))
    if ws.python != sys.executable:
        return {**info, "install": "the workspace's own environment (its container)"}
    if setting == "off" or not commands:
        return info
    venv = rt.out / VENV  # outside the workspace, so no detector or diff ever sees it
    python = venv / "bin" / "python"
    steps = [[sys.executable, "-m", "venv", "--system-site-packages", str(venv)]]
    steps += [[str(python), "-m", "pip", "install", "-q", *args] for args in commands]
    rt.log.emit(
        "tool_call",
        agent="tester",
        payload={"tool": "install", "args": {"commands": [" ".join(a) for a in commands]}},
    )
    for n, cmd in enumerate(steps):
        if n == 1:
            _see_host_packages(ws, python)
        code, out = ws.run(cmd, timeout=INSTALL_TIMEOUT)
        if code != 0:
            last = out.strip().splitlines()[-1][:200] if out.strip() else f"exit {code}"
            info["install"] = f"failed ({' '.join(cmd[2:5])}): {last}"
            rt.log.emit(
                "tool_result",
                agent="tester",
                payload={"tool": "install", "result": info["install"]},
            )
            return info
    ws.python = str(python)
    info.update(python=str(python), install=f"installed into {VENV} (next to the workspace)")
    rt.log.emit(
        "tool_result", agent="tester", payload={"tool": "install", "result": info["install"]}
    )
    return info
