import json
import shutil
from pathlib import Path

import pytest

from cleansweep.eval.hidden import _hidden_status

SRC = Path(__file__).resolve().parents[2] / "src" / "cleansweep"
TIER1 = Path(__file__).resolve().parents[2] / "data" / "splits" / "swebench_tier1.json"
needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


def test_guard_side_code_never_reads_patchdiff_tests():
    # only eval (hidden checks) and data (the loader) may touch PatchDiff's tests
    for package in ("guard", "sandbox", "workflow", "reviewer", "scheduler", "ranking"):
        for path in (SRC / package).rglob("*.py"):
            text = path.read_text()
            assert "hidden_tests" not in text and "patchdiff" not in text.lower(), path


class FakeWorkspace:
    """Collection fails when the files run together; each works on its own."""

    def __init__(self):
        self.calls = []

    def run_tests(self, paths):
        self.calls.append(list(paths or []))
        self.last_test_output = "ok" if len(paths) == 1 else "collection error"

    def parser(self, text, spec):
        if text != "ok":
            return {}
        return {f"{self.calls[-1][0]}::t": "PASSED"}

    spec = None


def test_hidden_files_run_one_at_a_time_when_together_fails():
    ws = FakeWorkspace()
    status = _hidden_status(ws, ["a.py", "b.py"])
    assert status == {"a.py::t": "PASSED", "b.py::t": "PASSED"}
    assert ws.calls == [["a.py", "b.py"], ["a.py"], ["b.py"]]


def _first_target() -> tuple[str, str, str]:
    entry = json.loads(TIER1.read_text())[0]
    return f"swebench:{entry['instance_id']}:{entry['agent']}", entry["instance_id"], entry["agent"]


@pytest.mark.docker
@needs_docker
def test_sweep_workspace_has_no_patchdiff_tests(sandbox_cfg):
    from cleansweep.data import load_agent_patches
    from cleansweep.data.swebench import data_path
    from cleansweep.sandbox import open_workspace

    target, instance_id, agent = _first_target()
    patch = next(p for p in load_agent_patches([agent]) if p.instance_id == instance_id)
    hidden = [data_path(rel).read_text() for rel in patch.hidden_tests]
    assert hidden
    ws = open_workspace(target, {**sandbox_cfg, "flaky_runs": 0})
    try:
        for path in Path(ws.path).rglob("*.py"):
            if ".git" not in path.parts:
                assert path.read_text(errors="replace") not in hidden, path
    finally:
        ws.close()


@pytest.mark.docker
@needs_docker
def test_no_cleanup_means_no_hidden_change(cfg):
    from cleansweep.eval import run_hidden_checks

    target, _, _ = _first_target()
    result = run_hidden_checks(target, "", cfg)
    assert result["available"] and result["applied"]
    assert result["behavior_changed"] is False
    assert result["patchdiff_files"] > 0 and result["patchdiff_tests"] > 0
