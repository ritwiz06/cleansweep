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


def plant(method, repo, seed, kind, removed, hidden=False):
    return {
        "method": method,
        "repo": repo,
        "seed": seed,
        "kind": kind,
        "removed": removed,
        "hidden_changed": hidden,
        "llm_calls": "4",
    }


def test_injection_tables_pool_seeds_and_pair_by_project_and_seed():
    tables = load()
    plants = []
    for seed in ("1", "2"):
        for repo in ("toy", "aaa"):
            plants += [
                plant("agentic", repo, seed, "slop", 1),
                plant("agentic", repo, seed, "trap", 0),
            ]
            single = repo == "aaa"
            plants += [
                plant("agentic-single_agent", repo, seed, "slop", 0, hidden=single),
                plant("agentic-single_agent", repo, seed, "trap", int(single), hidden=single),
            ]
    seeds = {(r["method"], r["seeds"]): r for r in tables.injection_seeds(plants)}
    assert seeds["agentic", "pooled"]["planted removed"] == "4/4"
    assert seeds["agentic", "seed 1"]["runs"] == 2
    assert seeds["agentic-single_agent", "pooled"]["hidden changed"] == "2/4"
    assert seeds["agentic-single_agent", "pooled"]["traps removed"] == 2
    paired = {r["comparison"]: r for r in tables.injection_paired(plants)}
    single = paired["agentic vs agentic-single_agent"]
    assert single["pairs"] == 4 and single["planted removed"] == "4 vs 0"
    assert single["hidden changed only first / only second"] == "0 / 2"
    assert "agentic vs agentic-no_research" not in paired  # no runs to pair


def test_p_values_below_four_places_are_not_shown_as_zero():
    tables = load()
    assert tables.p_value(0.06327) == 0.0633
    assert tables.p_value(3.05e-5) == "<0.0001"


def test_adaptive_investigation_is_paired_with_the_team_on_its_seed():
    tables = load()
    plants = []
    for repo in ("toy", "aaa"):
        plants += [plant("agentic", repo, "1", "slop", 1), plant("agentic", repo, "2", "slop", 1)]
        plants.append(plant("agentic-adaptive", repo, "1", "slop", int(repo == "toy")))
    paired = {r["comparison"]: r for r in tables.injection_paired(plants)}
    assert paired["agentic vs agentic-adaptive"]["pairs"] == 2
    assert paired["agentic vs agentic-adaptive"]["planted removed"] == "2 vs 1"
    timed = [{**p, "test_runs": "3", "minutes": "1.5"} for p in plants]
    rows = {(r["set"], r["method"]): r for r in tables.ablations([], timed)}
    assert rows["injected", "agentic-adaptive"]["planted found"] == "1/2"
