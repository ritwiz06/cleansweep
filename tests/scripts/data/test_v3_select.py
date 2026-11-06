import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "data" / "data_v3_select.py"
V3 = {
    "seed": 4,
    "licenses": ["MIT"],
    "inject": 1,
    "real": 2,
    "real_two_runs": 1,
    "min_py_files": 8,
    "max_test_seconds": 300,
    "autonomy": 3,
    "autonomy_quotas": {"no_tests": 1, "install_failed": 1},
}


def load():
    spec = importlib.util.spec_from_file_location("data_v3_select", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_features_read_the_test_style_build_and_layout():
    files = {
        "pyproject.toml": '[tool.poetry]\nname = "x"\n',
        "src/pkg/__init__.py": "",
        "src/pkg/core.py": "",
        "tests/test_core.py": "import unittest\n",
        "notes.ipynb": "{}",
        "Makefile": "test:\n\tpytest\n",
    }
    feats = load().features(sorted(files), files.get)
    assert feats["test_style"] == "unittest"
    assert feats["build"] == "poetry"
    assert feats["layout"] == "src"
    assert feats["notebooks"] == 1
    assert feats["makefile_test"] == 1
    assert load().features(["setup.py", "pkg/a.py"], lambda p: "")["test_style"] == "none"


def row(name, status="kept", reason="", **extra):
    base = {
        "full_name": name,
        "head_sha": "abc",
        "clone_url": "",
        "license": "MIT",
        "status": status,
        "reason": reason,
        "tests": "10",
        "pass_rate": "1.0",
        "test_seconds": "20",
        "test_style": "pytest",
        "build": "setuptools",
        "layout": "flat",
        "py_files": "12",
        "notebooks": "0",
        "packages": "1",
        "tox": "0",
        "nox": "0",
        "makefile_test": "0",
    }
    return base | extra


def test_split_is_disjoint_skips_v2_and_hidden_names_and_fills_autonomy_quotas():
    rows = [row(f"o/kept{i}") for i in range(6)]
    rows += [row("o/v2"), row("o/hidden"), row("o/gpl", license="GPL-3.0")]
    rows += [row("o/notests", "dropped", "fewer than 5 tests ran", test_style="none")]
    rows += [row("o/broken", "dropped", "install failed")]
    rows += [row("o/slow", "dropped", "tests over the time limit")]
    out = load().split(rows, V3, v2_runnable={"o/v2"}, hidden={"o/hidden"})
    inject = {r["full_name"] for r in out["inject"]}
    real = {r["full_name"] for r in out["real"]}
    autonomy = {r["full_name"] for r in out["autonomy"]}
    assert len(inject) == 1 and len(real) == 2 and len(autonomy) == 3
    assert not (inject & real or inject & autonomy or real & autonomy)
    assert not ({"o/v2", "o/hidden", "o/gpl"} & (inject | real | autonomy))
    assert {"o/notests", "o/broken"} <= autonomy
    assert [r["runs"] for r in out["real"]] == [2, 1]
    reserve = {r["full_name"] for r in out["reserve"]}
    assert len(reserve) == 3 and not reserve & (inject | real | autonomy)
    assert out == load().split(rows, V3, v2_runnable={"o/v2"}, hidden={"o/hidden"})
