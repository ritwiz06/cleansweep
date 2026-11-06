import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "exp_autonomy.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_autonomy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_run_completes_only_with_a_cleanup_verdict_and_no_traceback():
    auto = load()
    out = "progress\nResult: not verified by tests. 0 edits applied; 0 lines and 0 files removed.\n"
    assert auto.verdict_of(out) == "not verified by tests"
    report = {"stats": {"agentic": {"verdict": "stopped: setup.py failed, nothing applied"}}}
    assert auto.verdict_of("", report) == "stopped: setup.py failed, nothing applied"
    assert auto.classify(1, "not verified by tests", out, "") == (True, True, "")
    assert auto.classify(1, "everything runs", "", "Traceback (most recent call last):") == (
        False,
        False,
        "crash",
    )
    stop = "stopped: Docker is not running; start it, nothing applied"
    assert auto.classify(1, stop, "", "") == (True, False, "docker")
    assert auto.classify(None, "", "", "") == (False, False, "timeout")
    assert auto.classify(0, "something new", "", "") == (False, False, "unknown verdict")


def test_summary_counts_each_pass_with_a_wilson_interval():
    auto = load()
    rows = [
        {
            "pass": 1,
            "completed": True,
            "valid_verdict": True,
            "verdict": "everything runs",
            "failure": "",
        },
        {"pass": 1, "completed": False, "valid_verdict": False, "verdict": "", "failure": "crash"},
        {
            "pass": 2,
            "completed": True,
            "valid_verdict": True,
            "verdict": "nothing applied",
            "failure": "",
        },
    ]
    first, second = auto.summarize(rows)
    assert (first["runs"], first["completed"], first["rate"]) == (2, 1, 0.5)
    assert first["failures"] == "crash: 1" and first["verdicts"] == "everything runs: 1"
    assert first["ci_low"] < 0.5 < first["ci_high"] and first["valid_verdict"] == 1
    assert second["rate"] == 1.0
