import importlib.util
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
