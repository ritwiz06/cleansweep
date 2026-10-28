import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.sandbox.swebench_docker import (
    command_for,
    drop_files,
    eval_lines,
    patch_files,
    to_result,
)

PATCH = (
    "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-x\n+y\n"
    "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n"
    "+++ b/tests/test_a.py\n@@ -1 +1 @@\n-x\n+y\n"
)
SCRIPT = """#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
export LANG=en_US.UTF-8
git config --global --add safe.directory /testbed
git status
python -m pip install -e .
git checkout abc tests/test_a.py
git apply -v - <<'EOF_1'
EOF_1
: '>>>>> Start Test Output'
pytest -rA tests/test_a.py
: '>>>>> End Test Output'
"""


def test_patch_files_and_drop_files():
    assert patch_files(PATCH) == ["pkg/a.py", "tests/test_a.py"]
    kept = drop_files(PATCH, {"tests/test_a.py"})
    assert patch_files(kept) == ["pkg/a.py"] and kept.endswith("+y\n")


def test_eval_lines_keep_setup_and_find_the_command():
    setup, command = eval_lines(SCRIPT)
    assert setup == ["export LANG=en_US.UTF-8", "python -m pip install -e ."]
    assert command == "pytest -rA tests/test_a.py"


def test_command_for_uses_the_instance_directive_style():
    pytest_cmd = "pytest -rA tests/test_a.py"
    assert command_for(pytest_cmd, ["tests/test_a.py"], None) == pytest_cmd
    assert command_for(pytest_cmd, ["tests/test_a.py"], ["tests/test_b.py"]) == (
        "pytest -rA tests/test_b.py"
    )
    django = "./tests/runtests.py --verbosity 2 --parallel 1 auth_tests.test_views"
    files = ["tests/auth_tests/test_views.py"]
    assert command_for(django, files, ["tests/mail/tests.py"]) == (
        "./tests/runtests.py --verbosity 2 --parallel 1 mail.tests"
    )


def test_to_result_ignores_flaky_tests():
    status = {"a": "PASSED", "b": "FAILED", "c": "ERROR", "d": "SKIPPED", "e": "FAILED"}
    result = to_result(status, {"e"}, 1.0)
    assert (result.passed, result.failed, result.errors, result.skipped) == (1, 1, 1, 1)
    assert result.failed_ids == ["b", "c"] and not result.ok
    assert to_result({}, set(), 0.0).failed_ids == ["<no test results>"]


def _tier1_targets(n: int) -> list[str]:
    path = Path(__file__).resolve().parents[2] / "data" / "splits" / "swebench_tier1.json"
    seen, out = set(), []
    for entry in json.loads(path.read_text()):
        if entry["instance_id"] not in seen:
            seen.add(entry["instance_id"])
            out.append(f"swebench:{entry['instance_id']}:{entry['agent']}")
    return out[:n]


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@pytest.mark.docker
@needs_docker
@pytest.mark.parametrize("target", _tier1_targets(3))
def test_tier1_instance_opens_runs_and_rolls_back(target, sandbox_cfg):
    from cleansweep.guard import apply_edit
    from cleansweep.sandbox import open_workspace

    ws = open_workspace(target, {**sandbox_cfg, "flaky_runs": 1})
    try:
        log = subprocess.run(
            ["git", "log", "--format=%s"], cwd=ws.path, capture_output=True, text=True
        ).stdout.split("\n")
        assert log[:2] == ["agent patch", "base"]
        result = ws.run_tests(None)
        section = ws.last_test_output.split(">>>>> Start Test Output", 1)[-1]
        status = ws.parser(section.split(">>>>> End Test Output", 1)[0], ws.spec)
        assert all(status.get(t) == "PASSED" for t in ws.row["PASS_TO_PASS"])
        assert result.passed > 0

        touched = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=ws.path,
            text=True,
            capture_output=True,
        ).stdout.split()
        path = next(f for f in touched if f.endswith(".py"))
        start = ws.checkpoint("before format")
        item = CleanupItem("f", CodeUnit(path, "file"), "format", "format", "safe", "r")
        assert apply_edit(ws, item)
        assert ws.run([ws.python, "-m", "py_compile", path])[0] == 0
        ws.rollback(start)
        assert ws.diff(start) == ""
    finally:
        ws.close()
    alive = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name={ws.container}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert alive == "" and not Path(ws.path).exists()


@pytest.mark.docker
@needs_docker
def test_probe_harness_runs_inside_the_container(sandbox_cfg):
    from cleansweep.guard.difftest import run_harness
    from cleansweep.sandbox import open_workspace

    ws = open_workspace(_tier1_targets(1)[0], {**sandbox_cfg, "flaky_runs": 0})
    try:
        probe = (
            "def make_cases():\n"
            "    import sys\n"
            "    return [('major', lambda: sys.version_info[0])]\n"
        )
        spec = {"paths": [".", "src"], "probes": ["t0"], "modules": ["_pytest.unittest"]}
        out = run_harness(ws, spec, {"t0.py": probe}, {})
        assert out["probes"]["t0"] == {"ok": True, "cases": {"major": "3"}}
        assert out["modules"]["_pytest.unittest"]["ok"]
    finally:
        ws.close()


@pytest.mark.docker
@needs_docker
def test_runner_mode_probes_import_django_admin(sandbox_cfg):
    from cleansweep.guard.difftest import run_harness
    from cleansweep.sandbox import open_workspace

    target = next(t for t in _tier1_targets(4) if ":django__" in t)
    ws = open_workspace(target, {**sandbox_cfg, "flaky_runs": 0})
    try:
        probe = (
            "def make_cases():\n"
            "    from django.contrib.admin.options import ModelAdmin\n"
            "    from django.contrib.auth.models import User\n"
            "    return [\n"
            "        ('admin', lambda: ModelAdmin.__name__),\n"
            "        ('model', lambda: User._meta.label),\n"
            "    ]\n"
        )
        spec = {"paths": ["."], "probes": ["t0"], "modules": ["django.contrib.admin.options"]}
        direct = run_harness(ws, spec, {"t0.py": probe}, {}, "direct")
        assert not direct["probes"]["t0"]["ok"]  # no settings outside the test run
        runner = run_harness(ws, spec, {"t0.py": probe}, {}, "runner")
        assert runner["probes"]["t0"] == {
            "ok": True,
            "cases": {"admin": "'ModelAdmin'", "model": "'auth.User'"},
        }
        assert runner["modules"]["django.contrib.admin.options"]["ok"]
    finally:
        ws.close()


@pytest.mark.docker
@needs_docker
def test_patches_that_need_fuzz_and_crlf_files_open_and_sync(sandbox_cfg):
    from cleansweep.sandbox import open_workspace

    # the PatchDiff patch applies only with `patch --fuzz` in the container
    ws = open_workspace("swebench:sympy__sympy-12096:OpenHands", {**sandbox_cfg, "flaky_runs": 0})
    ws.close()
    # the agent created CRLF files; deleting them must still reach the container
    ws = open_workspace(
        "swebench:sphinx-doc__sphinx-7910:LearnByInteract", {**sandbox_cfg, "flaky_runs": 0}
    )
    try:
        shutil.rmtree(Path(ws.path) / "test_docs")
        ws.sync()
        code, out = ws._exec("find test_docs -type f | wc -l", 60)
        assert code == 0 and out.strip().splitlines()[-1] == "0"
    finally:
        ws.close()
