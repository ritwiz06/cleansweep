import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_audit_confirm.py"
A, B, C = "a" * 12, "b" * 12, "c" * 12


def load():
    spec = importlib.util.spec_from_file_location("exp_audit_confirm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_test_also_covers_the_checks_that_cite_its_edit():
    confirm = load()
    known = {
        A: {"evidence": "removes f."},
        B: {"evidence": f"the same change as {A} (same file, another seed): removes f."},
        C: {"evidence": f"removes g (as {A})."},
    }
    assert confirm.same_change(known) == {A: [B]}


def test_before_holds_the_runs_earlier_kept_edits_to_the_same_file():
    confirm = load()
    plan = [("1", "a.py"), ("2", "b.py"), ("3", "a.py"), ("4", "a.py")]
    report = {
        "plan": {
            "items": [{"item_id": i, "category": "dead_code", "unit": {"path": p}} for i, p in plan]
        },
        "results": [
            {"item_id": i, "status": s, "diff": f"d{i}"}
            for i, s in [("1", "kept"), ("2", "kept"), ("3", "rolled_back"), ("4", "kept")]
        ],
    }
    assert confirm.earlier_edits(report, "4", "a.py") == ["d1"]
    assert confirm.earlier_edits(report, "1", "a.py") == []


def test_a_confirmed_test_and_a_no_test_reason_go_into_the_evidence(tmp_path):
    confirm = load()
    folder = tmp_path / A
    folder.mkdir()
    (folder / f"test_{A}.py").write_text('"""Calls f; after the edit it raises."""\n')
    check = {
        "edit": A,
        "verdict": "wrong",
        "evidence": "removes f.",
        "checked_by": "reading (LLM-judged)",
        "kind": "public name",
    }
    done = confirm.recorded(check, {"confirmed": True}, folder)
    assert done["checked_by"] == "targeted test"
    assert done["evidence"].endswith(
        "Targeted test (passes before the edit, fails after): Calls f; after the edit it raises."
    )
    assert confirm.recorded(done, {"confirmed": True}, folder) == done
    assert confirm.recorded(check, {"confirmed": False}, folder) == check
    (folder / "no_test.txt").write_text("it needs torch,\nwhich the run's environment lacks.\n")
    noted = confirm.recorded(check, {"confirmed": False}, folder)
    assert noted["checked_by"] == "reading (LLM-judged)"
    assert noted["evidence"].endswith(
        "No targeted test: it needs torch, which the run's environment lacks."
    )


def test_an_earlier_test_not_confirmed_here_goes_back_to_reading(tmp_path):
    confirm = load()
    folder = tmp_path / A
    folder.mkdir()
    check = {
        "edit": A,
        "verdict": "wrong",
        "evidence": "x.",
        "checked_by": "targeted test",
        "kind": "",
    }
    out = confirm.recorded(check, None, folder)
    assert out["checked_by"] == "reading (LLM-judged)"
    assert out["evidence"] == "x. The earlier test ran outside the run's environment."


def test_package_names_compare_as_pip_normalizes_them():
    confirm = load()
    assert confirm._name("Pydantic_Settings") == confirm._name("pydantic-settings")
    assert confirm._name("python.dotenv") == "python-dotenv"
