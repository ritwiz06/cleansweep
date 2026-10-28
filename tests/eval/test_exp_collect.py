import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "exp_collect.py"


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
