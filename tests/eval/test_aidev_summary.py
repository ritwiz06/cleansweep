import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "exp_aidev_summary.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_aidev_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def item(i, category, lane="safe", action="delete_lines"):
    return {"item_id": i, "category": category, "lane": lane, "action": action}


def report(method, items, results, hidden):
    return {
        "_method": method,
        "_repo": "o/r",
        "plan": {"items": items},
        "results": results,
        "stats": {"lines_removed": 5, "files_removed": 1, "hidden": hidden},
    }


def test_summary_splits_files_from_code_and_rollbacks_by_check():
    summary = load()
    rep = report(
        "cleansweep-advisory",
        [
            item("a", "leftover_file", action="delete_file"),
            item("b", "dead_code"),
            item("c", "duplicate"),
            item("d", "unused_dependency"),
        ],
        [
            {"item_id": "a", "status": "kept", "diff": "d"},
            {"item_id": "b", "status": "kept", "diff": "d"},
            {"item_id": "c", "status": "rolled_back", "diff": "", "notes": "probes failed: x"},
            {"item_id": "d", "status": "skipped", "notes": "edit could not be applied"},
        ],
        {"available": True, "behavior_changed": False, "alt_files": 2, "alt_tests": 9},
    )
    cats, methods = summary.summarize([rep])
    assert methods[0]["applied_files"] == 1 and methods[0]["applied_code"] == 1
    assert methods[0]["rolled_back_probes"] == 1 and methods[0]["hidden_checked"] == 1
    assert methods[0]["could_not_apply"] == 1
    assert {c["category"]: c["applied"] for c in cats} == {
        "dead_code": 1,
        "duplicate": 0,
        "leftover_file": 1,
        "unused_dependency": 0,
    }
    assert summary.hidden_rows([rep]) == [
        {"repo": "o/r", "test_files": 2, "stable_tests": 9, "passing": 0, "unstable": 0}
    ]
    assert summary.rollback_check({"notes": "tests failed: new failing tests"}) == "tests"


DIFF = """diff --git a/pkg/cli.py b/pkg/cli.py
--- a/pkg/cli.py
+++ b/pkg/cli.py
@@ -1,6 +1,2 @@
-def format_score(x):
-    return f"{x:.2f}"
-def main(
+def main(
     argv=None,
diff --git a/tools/bench.py b/tools/bench.py
deleted file mode 100644
--- a/tools/bench.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""

TESTS = """from pkg.cli import main


def test_main():
    assert main() is None


def test_format_score():
    from pkg import cli

    assert cli.format_score(1) == "1.00"
"""


def test_hidden_changes_from_deleted_code(tmp_path):
    summary = load()
    (tmp_path / "test_cs_alt_0.py").write_text(TESTS)
    (tmp_path / "test_cs_alt_1.py").write_text("def test_bench():\n    pass\n")
    sources = {"test_cs_alt_0.py": "pkg/cli.py", "test_cs_alt_1.py": "tools/bench.py"}
    (tmp_path / "meta.json").write_text(json.dumps({"sources": sources}))
    assert summary.removed_names(DIFF) == {"format_score"}

    def run(changed):
        hidden = {"available": True, "behavior_changed": True, "alt_changed": changed}
        rep = report("tools_only", [], [], hidden) | {"_tests": tmp_path}
        rep["stats"]["final_diff"] = DIFF
        return rep

    deleted = run(["_hidden_checks.test_cs_alt_0::test_format_score"])
    assert summary.hidden_cause(deleted) == "deleted code"
    in_deleted_file = run(["_hidden_checks.test_cs_alt_1::test_bench"])
    assert summary.hidden_cause(in_deleted_file) == "deleted code"
    behavior = run(["_hidden_checks.test_cs_alt_0::test_main"])
    assert summary.hidden_cause(behavior) == "behavior"
    _, methods = summary.summarize([deleted, behavior])
    assert methods[0]["hidden_deleted"] == 1 and methods[0]["hidden_behavior"] == 1
    rows = summary.change_rows([deleted, in_deleted_file])
    assert [r["deleted_code_used"] for r in rows] == ["format_score", "bench.py"]


def test_format_and_import_edits_are_kept_out_of_the_code_lines():
    summary = load()
    rep = report(
        "guard_tests_only",
        [item("f", "format"), item("i", "unused_import"), item("d", "dead_code")],
        [
            {"item_id": "f", "status": "kept", "diff": "-a\n+b\n+c\n+d\n"},
            {"item_id": "i", "status": "kept", "diff": "-import os\n"},
            {"item_id": "d", "status": "kept", "diff": "--- a/q.py\n+++ b/q.py\n-x = 1\n-y = 2\n"},
        ],
        {},
    )
    cats, methods = summary.summarize([rep])
    assert methods[0]["applied_format"] == 1 and methods[0]["applied_import"] == 1
    assert methods[0]["lines_removed_code"] == 2
    assert {c["category"]: c["lines_net"] for c in cats} == {
        "dead_code": 2,
        "format": -2,
        "unused_import": 1,
    }
    row = summary.large_rows([rep], limit=2)[0]
    assert row["applied"] == 3 and row["format"] == "1 / -2" and row["dead_code"] == "1 / 2"
    assert summary.large_rows([rep]) == []


def test_load_takes_each_run_from_the_first_folder_and_sets_excluded_repos_apart(tmp_path):
    summary = load()

    def write(clone, folder, name, lines):
        path = tmp_path / clone / "results" / "raw" / folder
        path.mkdir(parents=True, exist_ok=True)
        data = {"plan": {"items": []}, "results": [], "stats": {"lines_removed": lines}}
        (path / f"{name}.json").write_text(json.dumps(data))
        return path

    (tmp_path / "b" / ".cleansweep" / "hidden_tests" / "aidev_o_r@abc").mkdir(parents=True)
    grid = write("a", "grid", "o__r__tools_only", 5)
    write("a", "grid", "o__x__tools_only", 1)
    rerun = write("b", "rerun", "o__r__tools_only", 9)
    write("b", "rerun", "o__r__one_shot_llm", 7)
    reports, excluded = summary.load([grid, rerun], ["o__x"])
    lines = {(r["_method"], r["stats"]["lines_removed"]) for r in reports}
    assert lines == {("tools_only", 5), ("one_shot_llm", 7)}
    assert [r["_repo"] for r in excluded] == ["o/x"]
    one_shot = next(r for r in reports if r["_method"] == "one_shot_llm")
    assert one_shot["_tests"].name == "aidev_o_r@abc"


def test_repos_count_only_with_a_run_for_every_method():
    summary = load()
    reports = [
        {"_repo": "o/r", "_method": "tools_only"},
        {"_repo": "o/r", "_method": "one_shot_llm"},
        {"_repo": "o/s", "_method": "tools_only"},
    ]
    complete, running = summary.complete_runs(reports)
    assert [r["_repo"] for r in complete] == ["o/r", "o/r"] and running == ["o/s"]
