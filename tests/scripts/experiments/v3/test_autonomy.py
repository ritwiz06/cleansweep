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


def test_environment_categories_are_read_from_the_evidence():
    auto = load()
    assert auto.environment("stopped: x", "", "", py_files=0) == "not a Python project"
    assert auto.environment("", "RuntimeError: CUDA not available", "", 3) == "needs a GPU"
    out = "Max retries exceeded with url: /v1 (Name or service not known)"
    assert auto.environment("", out, "", 3) == "needs the network after install"
    assert auto.environment("", "error: command 'gcc' failed", "", 3).startswith("needs a native")
    assert auto.environment("stopped: an agent failed", "", "", 3) == ""


def test_the_adjusted_rate_leaves_environment_impossible_runs_out():
    auto = load()
    rows = [
        {"pass": 1, "completed": True, "valid_verdict": True, "verdict": "everything runs"},
        {
            "pass": 1,
            "completed": False,
            "valid_verdict": True,
            "verdict": "stopped: x",
            "failure": "other stop",
            "environment": "needs a GPU",
        },
        {
            "pass": 1,
            "completed": False,
            "valid_verdict": False,
            "verdict": "",
            "failure": "crash",
            "environment": "",
        },
    ]
    (row,) = auto.summarize(rows)
    assert (row["rate"], row["environment_impossible"], row["rate_without_them"]) == (
        0.333,
        1,
        0.5,
    )
