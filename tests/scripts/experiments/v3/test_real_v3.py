import importlib.util
import json
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


def test_tests_are_matched_to_their_modules():
    real = load()
    held = ["tests/test_a.py", "pkg/core_test.py"]
    assert real.in_modules("tests.test_a.TestX::test_one", held)
    assert real.in_modules("tests.test_a::test_two", held)
    assert real.in_modules("pkg.core_test::test_x", held)
    assert real.in_modules("::tests.test_a", held)
    assert not real.in_modules("tests.test_ab::test_one", held)
    assert not real.in_modules("tests.test_b::test_one", held)


def test_baseline_keeps_tests_that_pass_in_every_run_and_counts_flaky_ones():
    real = load()
    runs = [
        {
            "statuses": {
                "tests.test_a::t1": "passed",
                "tests.test_a::t2": "passed",
                "x::t": "passed",
            }
        },
        {
            "statuses": {
                "tests.test_a::t1": "passed",
                "tests.test_a::t2": "failed",
                "x::t": "passed",
            }
        },
        {
            "statuses": {
                "tests.test_a::t1": "passed",
                "tests.test_a::t2": "passed",
                "x::t": "passed",
            }
        },
    ]
    base = real.baseline(runs)
    assert base["stable_passing"] == ["tests.test_a::t1", "x::t"]
    assert base["flaky"] == ["tests.test_a::t2"]
    counts = real.held_counts(base, ["tests/test_a.py"])
    assert counts == {
        "test_functions": 3,
        "held_functions": 2,
        "held_share": 0.667,
        "held_passing": 1,
        "held_flaky": 1,
    }


def test_compare_splits_newly_failing_tests_into_held_out_and_visible():
    real = load()
    split = {
        "held": ["tests/test_a.py"],
        "baseline": {
            "stable_passing": ["tests.test_a::t1", "tests.test_b::t3", "tests.test_b::t4"],
            "flaky": ["tests.test_a::t5"],
        },
    }
    after = {
        "statuses": {
            "tests.test_a::t1": "failed",
            "tests.test_a::t5": "failed",
            "tests.test_b::t3": "passed",
        }
    }
    out = real.compare(split, after)
    assert out["held_changed"] == ["tests.test_a::t1"]  # the flaky t5 never counts
    assert out["visible_changed"] == ["tests.test_b::t4"]
    assert out["behavior_changed"] is True and out["visible_broken"] is True
    same = {"statuses": {t: "passed" for t in split["baseline"]["stable_passing"]}}
    assert real.compare(split, same)["behavior_changed"] is False


def test_a_second_run_gets_its_own_caches(tmp_path):
    cfg = load().run_cfg(2, tmp_path)
    assert cfg["core"]["llm"]["cache_path"] == str(tmp_path / "caches" / "llm.sqlite")
    assert cfg["core"]["guard"]["probe_cache_dir"] == str(tmp_path / "caches" / "probes")
    assert load().run_cfg(1, tmp_path)["core"]["llm"]["cache_path"] != str(
        tmp_path / "caches" / "llm.sqlite"
    )


def test_unusable_repositories_are_replaced_by_the_reserve_in_order(tmp_path, monkeypatch):
    real = load()
    monkeypatch.setattr(real, "RAW", tmp_path)
    skip = {"o/one_module", "r/also_bad"}

    def prepare(full_name, entry, cfg):
        return {"skip": "fewer than two test modules"} if full_name in skip else {"base": "b"}

    repos = {"o/a": {"runs": 2}, "o/one_module": {"runs": 2}, "o/c": {"runs": 1}}
    spare = [{"full_name": "r/also_bad"}, {"full_name": "r/good"}, {"full_name": "r/unused"}]
    out = real.usable_set(repos, spare, {}, prepare)
    assert [n for n, _, _ in out] == ["o/a", "r/good", "o/c"]
    assert out[1][1]["runs"] == 2 and out[1][1]["replaces"] == "r/also_bad"
    log = json.loads((tmp_path / "set.json").read_text())["replacements"]
    assert [(x["replaced"], x["by"]) for x in log] == [
        ("o/one_module", "r/also_bad"),
        ("r/also_bad", "r/good"),
    ]


def test_a_diff_made_against_lf_applies_to_the_crlf_original(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_bytes(b"x = 1\r\ny = 2\r\nz = 3\r\n")
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,2 @@\n x = 1\n-y = 2\n z = 3\n"
    assert load().apply_loose(str(tmp_path), diff)
    assert b"y = 2" not in (tmp_path / "a.py").read_bytes()


def test_recheck_redoes_only_the_checks_whose_diff_did_not_apply(tmp_path, monkeypatch):
    real = load()
    project = tmp_path / "o__a"
    (project / "agentic-r1").mkdir(parents=True)
    (project / "aider-r1").mkdir()
    (project / "split.json").write_text(json.dumps({"base": "b"}))
    (project / "agentic-r1" / "heldout.json").write_text(json.dumps({"applied": False}))
    (project / "agentic-r1" / "final.diff").write_text("d\n")
    (project / "aider-r1" / "heldout.json").write_text(json.dumps({"applied": True}))
    seen = []

    def check(full_name, split, diff, cfg):
        seen.append((full_name, split["base"], diff))
        return {"applied": True, "behavior_changed": True}

    monkeypatch.setattr(real, "heldout_check", check)
    out = real.recheck(tmp_path, 1)
    assert seen == [("o/a", "b", "d\n")]
    assert [r["record"] for r in out] == ["o__a/agentic-r1"]
    assert json.loads((project / "agentic-r1" / "heldout.json").read_text())["behavior_changed"]


def test_run_two_covers_marked_projects_or_every_project():
    real = load()
    assert real.wants_run({"runs": 1}, 1)
    assert not real.wants_run({"runs": 1}, 2)
    assert real.wants_run({"runs": 2}, 2)
    assert real.wants_run({}, 2, every=True)
