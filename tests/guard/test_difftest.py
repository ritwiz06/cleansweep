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
