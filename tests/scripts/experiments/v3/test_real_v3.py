import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "exp_real_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_real_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_holds_out_half_the_test_modules_by_seed():
    real = load()
    files = [f"tests/test_{i}.py" for i in range(7)] + ["tests/conftest.py", "tests/helpers.py"]
    files += ["pkg/core.py", "pkg/core_test.py"]
    visible, held = real.split_tests(files, seed=4)
    assert len(held) == 4 and len(visible) == 4
    assert not set(visible) & set(held)
    assert "tests/conftest.py" not in held + visible and "pkg/core.py" not in held + visible
    assert (visible, held) == real.split_tests(list(reversed(files)), seed=4)
    assert (visible, held) != real.split_tests(files, seed=5)


def test_heldout_check_reports_modules_that_newly_fail(monkeypatch):
    real = load()
    split = {
        "base": "b",
        "held": ["tests/test_a.py"],
        "baseline": {"failed_ids": ["x"], "passed": 5},
    }
    monkeypatch.setattr(
        real,
        "run_tests_at",
        lambda target, tests, cfg, diff="": {
            "applied": True,
            "passed": 4,
            "failed_ids": ["x", "y"],
        },
    )
    out = real.heldout_check("o/a", split, "diff", {})
    assert out["newly_failing"] == ["y"] and out["behavior_changed"] is True
    monkeypatch.setattr(
        real,
        "run_tests_at",
        lambda target, tests, cfg, diff="": {"applied": True, "passed": 5, "failed_ids": ["x"]},
    )
    assert real.heldout_check("o/a", split, "diff", {})["behavior_changed"] is False


def test_a_second_run_gets_its_own_caches(tmp_path):
    cfg = load().run_cfg(2, tmp_path)
    assert cfg["core"]["llm"]["cache_path"] == str(tmp_path / "caches" / "llm.sqlite")
    assert cfg["core"]["guard"]["probe_cache_dir"] == str(tmp_path / "caches" / "probes")
    assert load().run_cfg(1, tmp_path)["core"]["llm"]["cache_path"] != str(
        tmp_path / "caches" / "llm.sqlite"
    )
