import json

import pytest

from cleansweep.agents.coverage_probes import probe_with_coverage
from cleansweep.agents.scripted import ScriptedLLM
from cleansweep.analysis import build_graph
from cleansweep.core.config import load_config
from cleansweep.sandbox import open_workspace

SOURCE = 'def sign(x):\n    if x > 0:\n        return "pos"\n    return "neg"\n'
POSITIVE = "def make_cases():\n    from pkg.m import sign\n    return [('one', lambda: sign(1))]\n"
NEGATIVE = (
    "def make_cases():\n    from pkg.m import sign\n"
    "    return [('minus', lambda: sign(-1)), ('zero', lambda: sign(0))]\n"
)
TARGET = "pkg/m.py::sign"


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "m.py").write_text(SOURCE)
    workspace = open_workspace(str(root), {"work_dir": str(tmp_path / "ws")})
    yield workspace
    workspace.close()


def _cfg(tmp_path):
    guard = load_config()["core"]["guard"]
    return {**guard, "probe_cache_dir": str(tmp_path / "probes"), "probe_mode": "direct"}


def _llm():
    first = json.dumps({"probes": [{"target": TARGET, "code": POSITIVE}]})
    more = json.dumps({"probes": [{"target": TARGET, "code": NEGATIVE}]})
    return ScriptedLLM([("not run yet", [more]), ("Target id: pkg/m.py::sign", [first])])


def _edit(ws, new_neg: str):
    graph = build_graph(ws.path)
    start = ws.checkpoint("before")
    path = f"{ws.path}/pkg/m.py"
    with open(path, "w") as f:
        f.write(SOURCE.replace('return "neg"', new_neg))
    return start, graph


def test_rounds_continue_until_the_changed_lines_are_covered(ws, tmp_path):
    start, graph = _edit(ws, 'return "n" + "eg"')  # same behavior, new code
    outcome, info = probe_with_coverage(ws, start, [], graph, _llm(), _cfg(tmp_path))
    assert info["rounds"] == 2 and info["coverage"] == 1.0 and info["target_lines"] == 1
    assert outcome is not None and outcome.same


def test_the_extra_round_catches_a_change_the_first_round_misses(ws, tmp_path):
    start, graph = _edit(ws, 'return "NEG"')  # a behavior change in the branch round 1 never runs
    one_round, info1 = probe_with_coverage(ws, start, [], graph, _llm(), _cfg(tmp_path), rounds=1)
    assert info1["coverage"] == 0.0 and one_round.same  # what v1's single round would conclude
    guided, info = probe_with_coverage(ws, start, [], graph, _llm(), _cfg(tmp_path))
    assert info["coverage"] == 1.0 and not guided.same
