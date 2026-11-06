import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "exp_autonomy.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_autonomy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_run_completes_only_with_a_report_a_known_verdict_and_no_traceback():
    auto = load()
    out = "progress\nResult: not verified by tests. 0 edits applied; 0 lines and 0 files removed.\n"
    assert auto.verdict_of(out) == "not verified by tests"
    assert auto.classify(1, out, "", report=True) == (True, "")
    assert auto.classify(1, out, "Traceback (most recent call last):\n", report=True) == (
        False,
        "crash",
    )
    assert auto.classify(None, "", "", report=False) == (False, "timeout")
    assert auto.classify(1, "", "cleansweep clean: install failed for x", report=False) == (
        False,
        "install",
    )
    assert auto.classify(0, "Result: something new.", "", report=True) == (
        False,
        "unknown verdict",
    )


def test_summary_counts_each_pass_with_a_wilson_interval():
    auto = load()
    rows = [
        {"pass": 1, "completed": True, "verdict": "everything runs", "failure": ""},
        {"pass": 1, "completed": False, "verdict": "", "failure": "crash"},
        {"pass": 2, "completed": True, "verdict": "nothing applied", "failure": ""},
    ]
    first, second = auto.summarize(rows)
    assert (first["runs"], first["completed"], first["rate"]) == (2, 1, 0.5)
    assert first["failures"] == "crash: 1" and first["verdicts"] == "everything runs: 1"
    assert first["ci_low"] < 0.5 < first["ci_high"]
    assert second["rate"] == 1.0
