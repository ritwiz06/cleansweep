import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v1" / "exp_collect.py"


def load_collect():
    spec = importlib.util.spec_from_file_location("exp_collect", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(method, diff, hidden, target="p1"):
    return {"target_set": "t2", "method": method, "hidden_changed": hidden}, {
        "_group": target,
        "_diff": diff,
    }


def test_a_hidden_change_that_the_same_edits_do_not_repeat_is_flaky():
    collect = load_collect()
    rows = [
        {**a, **b}
        for a, b in (
            row("advisory", "d1", 0),
            row("guard_tests_only", "d1", 1),  # same edits, changed: flaky
            row("tools_only", "d2", 1),  # other edits: a real change
            row("one_shot_llm", "d1", 1, target="p2"),  # another target
            row("tools_only", "d3", ""),  # invalid output
        )
    ]
    marked = collect.mark_flaky(rows)
    assert [r["hidden_flaky"] for r in marked] == [0, 1, 0, 0, 0]
    assert all(not any(k.startswith("_") for k in r) for r in marked)


EDITS = {
    "plan": {
        "items": [
            {"item_id": "f", "category": "format"},
            {"item_id": "i", "category": "unused_import"},
            {"item_id": "d", "category": "dead_code"},
            {"item_id": "u", "category": "duplicate"},
        ]
    },
    "results": [
        # reformatting adds more lines than it removes
        {"item_id": "f", "status": "kept", "diff": "--- a/x.py\n+++ b/x.py\n-a\n+b\n+c\n+d\n"},
        {"item_id": "i", "status": "kept", "diff": "--- a/x.py\n+++ b/x.py\n-import os\n"},
        # a deleted line that starts with "--" is a change, not a file header
        {
            "item_id": "d",
            "status": "repaired",
            "diff": "--- a/q.py\n+++ b/q.py\n-def f():\n--- -1\n-    return 1\n",
            "tests": {"duration_s": 250.0},
        },
        {"item_id": "u", "status": "rolled_back", "diff": "-x\n-y\n"},
    ],
}


def test_format_and_import_edits_are_counted_apart_from_the_lines_removed():
    collect = load_collect()
    assert collect.edit_counts(EDITS) == {
        "format_edits": 1,
        "import_edits": 1,
        "lines_removed_code": 3,
    }


def test_a_first_test_run_over_twice_the_baseline_is_overload_suspect():
    collect = load_collect()
    assert collect.slowdown(EDITS, 100) == {"test_slowdown": 2.5, "overload_suspect": 1}
    assert collect.slowdown(EDITS, 200) == {"test_slowdown": 1.25, "overload_suspect": 0}
    assert collect.slowdown(EDITS, None)["overload_suspect"] == ""


def _report(folder, name, lines, scope="agent_blame"):
    stats = {
        "lines_removed": lines,
        "files_removed": 0,
        "test_runs": 1,
        "llm_calls": 0,
        "minutes": 1.0,
        "hidden": {"available": True, "applied": True, "behavior_changed": False},
        **({"scope": {"kind": scope, "units": 3, "share": 0.1}} if scope else {}),
    }
    folder.mkdir(parents=True, exist_ok=True)
    report = {"plan": {"items": []}, "results": [], "stats": stats}
    (folder / f"{name}.json").write_text(json.dumps(report))


def test_aidev_reruns_fill_missing_runs_and_excluded_or_incomplete_repos_drop(
    tmp_path, monkeypatch
):
    collect = load_collect()
    monkeypatch.setattr(collect, "AIDEV_SPLIT", tmp_path / "missing.json")
    grid, rerun = tmp_path / "grid", tmp_path / "rerun"
    _report(grid, "o__r__tools_only", 5)
    _report(grid, "o__x__tools_only", 1)
    _report(rerun, "o__r__tools_only", 9)  # already in the grid
    _report(rerun, "o__r__one_shot_llm", 7)  # failed in the grid
    _report(rerun, "o__y__tools_only", 3)  # its other run is still going
    rows = collect.aidev_rows(grid, [rerun, tmp_path / "none"], ["o__x"])
    assert {(r["method"], r["lines_removed"]) for r in rows} == {
        ("tools_only", 5),
        ("one_shot_llm", 7),
    }


def test_oneshot_variants_discard_or_retry_a_reply_that_does_not_compile():
    collect = load_collect()

    def one_shot(target, lines, hidden):
        return {
            "target_set": "t2",
            "target": target,
            "method": "one_shot_llm",
            **dict.fromkeys(collect.OUTCOMES, 1),
            "lines_removed": lines,
            "hidden_changed": hidden,
            "_group": target,
            "_diff": f"d-{target}",
        }

    rows = [one_shot("ok", 5, 0), one_shot("bad", 9, 1), one_shot("unknown", 3, 0)]
    retry = {**one_shot("bad", 7, 0), "method": "one_shot_retry", "target_set": ""}
    out = collect.oneshot_variants(rows, {("t2", "ok"): False, ("t2", "bad"): True}, {"bad": retry})
    got = {(r["target"], r["method"]): (r["lines_removed"], r["hidden_changed"]) for r in out}
    assert got == {
        ("ok", "one_shot_compile"): (5, 0),
        ("ok", "one_shot_retry"): (5, 0),
        ("bad", "one_shot_compile"): (0, 0),  # the diff is discarded
        ("bad", "one_shot_retry"): (7, 0),
    }
    assert (
        next(r for r in out if r["method"] == "one_shot_retry" and r["target"] == "bad")[
            "target_set"
        ]
        == "t2"
    )
    # a set with a run still waiting for its rerun gets no retry rows at all
    partial = collect.oneshot_variants(rows, {("t2", "ok"): False, ("t2", "bad"): True}, {})
    assert {r["method"] for r in partial} == {"one_shot_compile"}


def test_aidev_rows_need_a_scope_record_and_skip_a_missing_scope(tmp_path, monkeypatch):
    import pytest

    collect = load_collect()
    monkeypatch.setattr(collect, "AIDEV_SPLIT", tmp_path / "none.json")
    grid, rerun = tmp_path / "grid", tmp_path / "rerun"
    _report(grid, "o__r__tools_only", 5, scope="missing")
    _report(rerun, "o__r__tools_only", 9)
    rows = collect.aidev_rows(grid, [rerun], [])
    assert [r["lines_removed"] for r in rows] == [9]  # the scoped rerun fills in
    _report(grid, "o__r__one_shot_llm", 3, scope=None)
    with pytest.raises(SystemExit, match="no complete scope record"):
        collect.aidev_rows(grid, [rerun], [])
    report = json.loads((grid / "o__r__one_shot_llm.json").read_text())
    report["stats"]["scope"] = {"kind": "agent_blame", "share": 0.1}  # no units
    (grid / "o__r__one_shot_llm.json").write_text(json.dumps(report))
    with pytest.raises(SystemExit, match="no complete scope record"):
        collect.aidev_rows(grid, [rerun], [])
