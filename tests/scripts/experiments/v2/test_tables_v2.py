import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_tables_v2.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_tables_v2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(method, target, repeat, hidden, lines, verdict=""):
    return {
        "target_set": "answer keys",
        "target": target,
        "method": method,
        "repeat": repeat,
        "verdict": verdict,
        "hidden_changed": hidden,
        "hits": 6,
        "total": 7,
        "code_lines_removed": lines,
        "lines_removed": lines,
        "llm_calls": 3,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "test_runs": 4,
        "minutes": 1.0,
    }


def test_runs_pair_by_target_and_repeat_and_no_outcome_counts_as_unchanged():
    tables = load()
    rows = [
        run("cleansweep-gatekeeper", "toy", 0, 0, 10),
        run("cleansweep-gatekeeper", "toy", 1, "", 10),
        run("agentic", "toy", 0, 1, 12, "everything runs"),
        run("agentic", "toy", 1, 0, 12, "everything runs"),
        run("agentic", "demo", 0, 1, 5, "not verified"),  # no v1 run to pair with
    ]
    (row,) = tables.eval_paired(rows)
    assert row["pairs"] == 2
    assert row["hidden changed only with method"] == 1
    assert row["hidden changed only with v1"] == 0
    assert row["code lines removed, method vs v1 (total)"] == "24 vs 20"
    table = {r["method"]: r for r in tables.eval_table(rows)}
    assert table["agentic"][tables.VERDICT_COLUMN] == "2 / 0 / 1"
    assert table["agentic"]["planted found"] == "18/21"
    assert table["cleansweep-gatekeeper"][tables.VERDICT_COLUMN] == "--"
