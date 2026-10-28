import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cleansweep.analysis import build_graph
from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.guard import Guard, verify
from cleansweep.guard.difftest import (
    HARNESS,
    ModuleCheck,
    Target,
    compare,
    get_probes,
    select_targets,
)
from cleansweep.guard.probe_harness import normalize
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import run_detectors
from cleansweep.sandbox import open_workspace

ROUNDING_PROBE = """
def make_cases():
    from shopcart.storage import _safe_round
    return [
        ("tie", lambda: _safe_round(0.125)),
        ("zero", lambda: _safe_round(0)),
        ("none", lambda: _safe_round(None)),
        ("negative", lambda: _safe_round(-1)),
    ]
"""

DISCOUNT_PROBE = """
def make_cases():
    from shopcart.discounts import _round_price
    return [("tie", lambda: _round_price(0.125)), ("big", lambda: _round_price(1e9 + 0.5))]
"""


def probe_reply(probes: dict[str, str]) -> str:
    return json.dumps({"probes": [{"target": k, "code": v} for k, v in probes.items()]})


def guard_cfg(tmp_path, **extra) -> dict:
    return {"diff_tests": True, "probe_cache_dir": str(tmp_path / "probes"), **extra}


def toy_item(ws, key: str) -> CleanupItem:
    items = run_detectors(ws.path, build_graph(ws.path))
    return next(i for i in items if i.unit.key == key and i.action == "replace_with")


def test_normalize_hides_addresses_and_ordering():
    class Box:
        def __init__(self):
            self.b, self.a = {3, 1, 2}, {"y": 1, "x": 2}

    assert normalize({"b": 1, "a": 2}) == normalize({"a": 2, "b": 1})
    assert normalize({3, 1, 2}) == "set(1, 2, 3)"
    assert normalize(Box()) == "Box({'a': {'x': 2, 'y': 1}, 'b': set(1, 2, 3)})"
    assert "0x" not in normalize(object())


def test_harness_records_results_and_exceptions(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def half(x):\n    return x / 2\n")
    (tmp_path / "p.py").write_text(
        "def make_cases():\n"
        "    from pkg import half\n"
        "    return [('two', lambda: half(2)), ('none', lambda: half(None))]\n"
    )
    spec = {"paths": ["."], "out": "out.json", "probes": [{"id": "t0", "file": "p.py"}]}
    spec["modules"] = ["pkg"]
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    subprocess.run([sys.executable, str(HARNESS), "spec.json"], cwd=tmp_path, check=True)
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["probes"]["t0"] == {"ok": True, "cases": {"two": "1.0", "none": "raises TypeError"}}
    assert out["modules"]["pkg"] == {"ok": True, "names": ["half"], "modules": []}


def test_compare_drops_unstable_cases_and_reports_mismatches():
    target = Target("m.py::f", "m", "f", "def f(): ...")
    run = {"probes": {"t0": {"ok": True, "cases": {"a": "1", "b": "2", "c": "7"}}}}
    rerun = {"probes": {"t0": {"ok": True, "cases": {"a": "1", "b": "3", "c": "7"}}}}
    after = {"probes": {"t0": {"ok": True, "cases": {"a": "1", "b": "9", "c": "8"}}}}
    out = compare([target], [], (run, rerun), after)
    assert (out.same, out.n_cases, out.n_unstable) == (False, 2, 1)
    assert out.mismatches == ["m.py::f [c]: before 7, after 8"]


def test_compare_module_check_allows_only_deleted_names():
    before = {"modules": {"m": {"ok": True, "names": ["a", "b", "c"]}}}
    after = {"modules": {"m": {"ok": True, "names": ["a"]}}}
    out = compare([], [ModuleCheck("m", {"b"})], (before, before), after)
    assert out.mismatches == ["module m lost public names: c"]


def test_formatting_is_not_a_change():
    before = "def f(x):\n    return x+1\n\ndef g(x):\n    return f(x)\n"
    after = "def f(x):\n    return x + 1\n\n\ndef g(x):\n    return f(x)\n"
    targets, checks = select_targets(".", {"m.py": (before, after)}, [], None, 10)
    assert targets == [] and checks == []


def test_replacement_probe_catches_half_up_rounding(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    assert item.keep_target == "shopcart/utils.py::round_price"
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})
    guard = Guard(toy_ws, llm, guard_cfg(tmp_path, repair=False))
    head = toy_ws.checkpoint("x")

    assert not guard.check_batch([item])  # the visible tests pass; only the probe sees it
    result = guard.results()[0]
    assert result.status == "rolled_back" and result.tests.failed == 0
    assert result.diff_check.same is False
    assert result.notes.startswith("probes failed")
    assert any("[tie]: before 0.13, after 0.12" in m for m in result.diff_check.mismatches)
    assert toy_ws.diff(head) == ""


def test_exact_duplicate_passes_its_probe(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/discounts.py::_round_price")
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: DISCOUNT_PROBE})})
    guard = Guard(toy_ws, llm, guard_cfg(tmp_path))
    assert guard.check_batch([item])
    result = guard.results()[0]
    assert result.status == "kept" and result.diff_check.same is True
    assert result.diff_check.n_cases >= 2


def test_probes_are_cached_by_source(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})
    path = "shopcart/storage.py"
    text = (Path(toy_ws.path) / path).read_text()
    target = Target(item.unit.key, "shopcart.storage", "_safe_round", text)
    cfg = guard_cfg(tmp_path)
    first, _ = get_probes([target], llm, cfg)
    second, _ = get_probes([target], llm, cfg)
    assert first == second == {item.unit.key: ROUNDING_PROBE}
    assert len(llm.calls) == 1
    changed = Target(item.unit.key, "shopcart.storage", "_safe_round", text + "\n# edited")
    get_probes([changed], llm, cfg)
    assert len(llm.calls) == 2


def test_diff_tests_off_keeps_the_trap(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})
    guard = Guard(toy_ws, llm, guard_cfg(tmp_path, diff_tests=False))
    assert guard.check_batch([item])
    assert guard.results()[0].status == "kept" and guard.results()[0].diff_check is None
    assert llm.calls == []


def test_module_check_catches_a_removed_reexport(tmp_path, sandbox_cfg):
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("from pkg.core import area\n")
    (src / "pkg" / "core.py").write_text("def area(w, h):\n    return w * h\n")
    (src / "test_core.py").write_text(
        "from pkg.core import area\n\n\ndef test_area():\n    assert area(2, 3) == 6\n"
    )
    ws = open_workspace(str(src), sandbox_cfg)
    item = CleanupItem(
        "i",
        CodeUnit("pkg/__init__.py", "import", "pkg.core.area", 1, 1),
        "unused_import",
        "remove_import",
        "safe",
        "unused",
    )
    guard = Guard(ws, None, guard_cfg(tmp_path))
    assert not guard.check_batch([item])
    assert guard.results()[0].diff_check.mismatches == ["module pkg lost public names: area"]
    ws.close()


def test_verify_runs_probes_on_two_workspaces(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    after = toy_ws.fork()
    assert after.apply_patch(item.patch)
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})
    cfg = guard_cfg(tmp_path, items=[item])
    ok, info = verify(toy_ws, after, [item.unit], llm, cfg)
    assert not ok and info["check"] == "probes"
    assert any("[tie]" in m for m in info["diff_check"].mismatches)
    after.close()


def test_probe_that_imports_a_removed_name_is_discarded():
    target = Target("m.py::caller", "m", "caller", "def caller(): ...")
    ok = {"probes": {"t0": {"ok": True, "cases": {"a": "1"}}}, "modules": {}}
    failed = {"ok": False, "error": "ImportError: cannot import name '_helper' from 'm'"}
    out = compare([target], [ModuleCheck("m", {"_helper"})], (ok, ok), {"probes": {"t0": failed}})
    assert out.same and out.n_cases == 0
    out = compare([target], [ModuleCheck("m", set())], (ok, ok), {"probes": {"t0": failed}})
    assert not out.same


def test_a_repair_that_undoes_the_edit_is_a_rollback(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})

    def revert(item, log, repo_dir, llm):
        out = subprocess.run(
            ["git", "diff", "-R", toy_ws.base], cwd=repo_dir, capture_output=True, text=True
        )
        return out.stdout

    guard = Guard(toy_ws, llm, guard_cfg(tmp_path), repair_fn=revert)
    assert not guard.check_batch([item])
    result = guard.results()[0]
    assert result.status == "rolled_back" and "the repair undid the edit" in result.notes


def test_verify_probe_touched_on_identical_copies(toy_ws, tmp_path):
    item = toy_item(toy_ws, "shopcart/storage.py::_safe_round")
    same = toy_ws.fork()
    llm = FakeLLM({"Target id": probe_reply({item.unit.key: ROUNDING_PROBE})})
    unit = CodeUnit("shopcart/storage.py", "function", "_safe_round")
    ok, info = verify(toy_ws, same, [unit], llm, guard_cfg(tmp_path, probe_touched=True))
    assert ok and info["diff_check"].n_cases == 5  # 4 probe cases + 1 module check
    ok, info = verify(toy_ws, same, [unit], llm, guard_cfg(tmp_path))
    assert ok and info["diff_check"].n_cases == 1  # nothing changed: only the module check
    same.close()


# A project whose code only works with its test setup: conftest.py "configures settings".
SETUP_REPO = {
    "pkg/__init__.py": "",
    "pkg/settings.py": "CONFIGURED = False\n",
    "pkg/core.py": (
        "from pkg import settings\n\n\n"
        "def scale(x):\n"
        "    if not settings.CONFIGURED:\n"
        "        raise RuntimeError('settings are not configured')\n"
        "    return x * 2\n"
    ),
    "tests/conftest.py": "from pkg import settings\n\nsettings.CONFIGURED = True\n",
    "tests/test_core.py": (
        "from pkg.core import scale\n\n\ndef test_scale():\n    assert scale(2) == 4\n"
    ),
}
SCALE_PROBE = (
    "def make_cases():\n"
    "    from pkg.core import scale\n"
    "    return [('two', lambda: scale(2)), ('zero', lambda: scale(0))]\n"
)


def setup_ws(tmp_path):
    src = tmp_path / "setup_repo"
    for rel, text in SETUP_REPO.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    return open_workspace(str(src), {"work_dir": str(tmp_path / "ws")})


def test_runner_mode_runs_probes_inside_the_test_setup(tmp_path):
    from cleansweep.guard.difftest import run_harness

    ws = setup_ws(tmp_path)
    spec = {"paths": ["."], "probes": ["t0"], "modules": ["pkg.core"]}
    direct = run_harness(ws, spec, {"t0.py": SCALE_PROBE}, {}, "direct")
    assert direct["probes"]["t0"]["cases"] == {
        "two": "raises RuntimeError",
        "zero": "raises RuntimeError",
    }
    runner = run_harness(ws, spec, {"t0.py": SCALE_PROBE}, {}, "runner")
    assert runner["probes"]["t0"] == {"ok": True, "cases": {"two": "4", "zero": "0"}}
    assert runner["modules"]["pkg.core"]["ok"]
    # the generated test file and the probe folder are gone, and git never saw them
    assert not list(Path(ws.path).rglob("test_cs_probe_*.py"))
    assert not (Path(ws.path) / "_probes").exists() or not any(
        (Path(ws.path) / "_probes").iterdir()
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ws.path, capture_output=True, text=True
    )
    assert status.stdout == ""
    ws.close()


def test_runner_test_file_finds_the_harness_from_its_folder(tmp_path):
    from cleansweep.guard.difftest import runner_test

    code = runner_test("_probes/abc123", "tests/unit/test_cs_probe_abc123.py")
    assert "os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..')" in code
    assert "'_probes/abc123/harness.py'" in code and "'_probes/abc123/spec.json'" in code
    compile(code, "<generated>", "exec")
    assert "'.'" in runner_test("_probes/x", "test_cs_probe_x.py")


def test_verify_in_runner_mode_catches_what_direct_mode_discards(tmp_path):
    before = setup_ws(tmp_path)
    after = before.fork()
    core = Path(after.path) / "pkg" / "core.py"
    core.write_text(core.read_text().replace("return x * 2", "return x * 2 if x else 1"))
    unit = CodeUnit("pkg/core.py", "function", "scale")
    llm = FakeLLM({"Target id": probe_reply({unit.key: SCALE_PROBE})})
    ok, info = verify(before, after, [unit], llm, guard_cfg(tmp_path, probe_mode="direct"))
    assert ok and info["probe_mode"] == "direct"  # the tests pass; the probes can't run
    ok, info = verify(before, after, [unit], llm, guard_cfg(tmp_path, probe_mode="runner"))
    assert not ok and info["check"] == "probes" and info["probe_mode"] == "runner"
    assert any("[zero]" in m for m in info["diff_check"].mismatches)
    before.close()
    after.close()


def test_probe_mode_auto_and_cache_keys(tmp_path):
    from cleansweep.guard.difftest import PROMPT_VERSION, RUNNER_NOTE, _prompt, probe_mode

    ws = setup_ws(tmp_path)
    assert probe_mode(ws, {}) == "direct"
    assert probe_mode(ws, {"probe_mode": "runner"}) == "runner"
    ws.probe_runner = True  # what SWE-bench and AIDev workspaces say
    assert probe_mode(ws, {}) == "runner"
    assert probe_mode(ws, {"probe_mode": "direct"}) == "direct"
    ws.close()
    target = Target("pkg/core.py::scale", "pkg.core", "scale", "def scale(x): ...")
    old = hashlib.sha256(f"{PROMPT_VERSION}\n{target.key}\n{target.source}".encode()).hexdigest()
    assert target.cache_key == target.key_for("direct") == old[:20]  # direct caches stay valid
    assert target.key_for("runner") != target.cache_key
    assert RUNNER_NOTE in _prompt([target], "runner") and RUNNER_NOTE not in _prompt([target])


def test_harness_main_puts_back_what_it_changed(tmp_path):
    import os
    import socket

    from cleansweep.guard import probe_harness

    (tmp_path / "p.py").write_text("def make_cases():\n    return [('one', lambda: 1)]\n")
    spec = {"paths": ["."], "out": "out.json", "probes": [{"id": "t0", "file": "p.py"}]}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    cwd, path, connect = os.getcwd(), list(sys.path), socket.socket.connect
    probe_harness.main(str(tmp_path / "spec.json"), str(tmp_path))
    assert json.loads((tmp_path / "out.json").read_text())["probes"]["t0"]["cases"] == {"one": "1"}
    assert (os.getcwd(), sys.path, socket.socket.connect) == (cwd, path, connect)
