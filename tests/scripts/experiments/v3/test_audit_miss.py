import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_audit_miss.py"
A, B, C, T = "a" * 12, "b" * 12, "c" * 12, "d" * 12


def load():
    spec = importlib.util.spec_from_file_location("exp_audit_miss", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_population_holds_the_no_votes_of_the_four_methods():
    miss = load()
    rows = [
        {"edit": A, "method": "agentic", "source": "injected"},
        {"edit": A, "method": "agentic", "source": "injected"},
        {"edit": B, "method": "cleansweep", "source": "injected"},
        {"edit": B, "method": "cleansweep-gatekeeper", "source": "aidev"},
        {"edit": C, "method": "agentic", "source": "swebench_t2"},
        {"edit": A, "method": "one_shot_llm", "source": "injected"},
    ]
    audit = {A: {"answer": "no"}, B: {"answer": "no"}, C: {"answer": "yes"}}
    assert miss.population(rows, audit) == {
        ("agentic", "injected"): {A: 2},
        ("cleansweep-gatekeeper", "injected"): {B: 1},
        ("cleansweep-gatekeeper", "AIDev"): {B: 1},
    }


def test_the_allocation_is_proportional_with_one_from_each_set():
    miss = load()
    sizes = {"injected": 647, "answer keys": 28, "real projects": 14, "AIDev": 9}
    assert miss.allocate(sizes, 25) == {
        "injected": 22,
        "answer keys": 1,
        "real projects": 1,
        "AIDev": 1,
    }
    assert miss.allocate({"injected": 90, "AIDev": 10}, 10) == {"injected": 9, "AIDev": 1}
    assert miss.allocate({"injected": 3, "AIDev": 1}, 25) == {"injected": 3, "AIDev": 1}


def test_the_draw_is_deterministic_stratified_and_weighted():
    miss = load()
    big = {f"{i:012x}": 1 + i % 2 for i in range(200)}
    pop = {
        ("agentic", "injected"): big,
        ("agentic", "AIDev"): {A: 1, B: 3},
        ("agentic-single_agent", "injected"): {C: 1},
    }
    edits = {e: {"project": "p", "path": "f.py"} for e in [*big, A, B, C]}
    first = miss.draw(pop, edits)
    assert first == miss.draw(pop, edits)
    picked = first["edits"]
    team = [e for e in picked if e["method"] == "agentic"]
    assert len(team) == miss.PER_METHOD
    assert sum(e["target_set"] == "AIDev" for e in team) == 1
    assert len({e["edit"] for e in team}) == miss.PER_METHOD
    for e in team:
        assert e["kept"] == pop[("agentic", e["target_set"])][e["edit"]]
        assert e["weight"] == {"injected": 200 / 24, "AIDev": 2.0}[e["target_set"]]
    assert [e["edit"] for e in picked if e["method"] == "agentic-single_agent"] == [C]
    strata = {(s["method"], s["target_set"]): s for s in first["strata"]}
    assert strata[("agentic", "AIDev")] == {
        "method": "agentic",
        "target_set": "AIDev",
        "population": 2,
        "kept": 4,
        "sampled": 1,
        "trap_edits": 0,
        "traps": 0,
    }
    traps = miss.draw(pop, edits, {B})
    assert (traps["strata"][0]["trap_edits"], traps["strata"][0]["traps"]) == (1, 3)
    assert {e["edit"] for e in traps["edits"] if e["trap"]} <= {B}


def test_no_hits_in_25_give_a_wilson_upper_bound_of_13_percent():
    miss = load()
    low, high = miss.wilson(0.0, 25)
    assert low == 0.0
    assert high == pytest.approx(0.1332, abs=1e-4)
    rate, low, high = miss.estimate([{"weight": 2.0, "kept": 1}] * 4, [True, False, False, False])
    assert rate == 0.25
    assert (low, high) == miss.wilson(0.25, 4)


def test_the_table_counts_trap_removals_and_estimates_the_rest():
    miss = load()
    cell = {"method": "agentic", "target_set": "injected", "population": 100, "kept": 110}
    sample = {
        "strata": [
            {**cell, "trap_edits": 10, "traps": 12},
            {"method": "agentic", "target_set": "AIDev", "population": 10, "kept": 10},
            {"method": "cleansweep-gatekeeper", "target_set": "injected", "population": 50},
        ],
        "edits": [
            {"edit": A, "method": "agentic", "target_set": "injected", "kept": 1},
            {"edit": B, "method": "agentic", "target_set": "injected", "kept": 2},
            {"edit": T, "method": "agentic", "target_set": "injected", "kept": 1, "trap": True},
            {"edit": C, "method": "agentic", "target_set": "AIDev", "kept": 1},
            {"edit": A, "method": "cleansweep-gatekeeper", "target_set": "injected", "kept": 1},
        ],
    }
    for s in sample["strata"]:
        s.setdefault("trap_edits", 0)
        s.setdefault("traps", 0)
        s.setdefault("kept", s["population"])
    for e in sample["edits"]:
        e.setdefault("trap", False)
    results = {e: {"confirmed": e != B} for e in (A, B, C, T)}
    readings = {A: {"verdict": "wrong"}, B: {"verdict": "wrong"}, C: {"verdict": "debatable"}}
    readings[T] = {"verdict": "wrong"}
    written = {A: "test", B: "test", C: "no_test", T: "test"}
    v2 = {"agentic": (3, 1), "cleansweep-gatekeeper": (2, 0)}
    rows = {
        (r["tier"], r["method"]): r for r in miss.table_rows(sample, results, readings, v2, written)
    }
    # the rest of agentic/injected: 90 edits, 2 sampled (weight 45); AIDev: weight 10
    team = rows[("confirmed", "agentic")]
    assert (team["sampled"], team["tests_written"], team["no_test"]) == (4, 3, 1)
    assert (team["fails_after"], team["wrong"], team["debatable"]) == (3, 2, 1)
    assert (team["trap_census"], team["sampled_trap_removals"]) == (12, 1)
    assert (team["no_kept_code_edits"], team["other_no_kept_code_edits"]) == (120, 108)
    assert team["miss_rate_estimate"] == round(45 / 145, 4)
    assert team["missed_estimate"] == round(45 / 145 * 108, 1)
    assert team["corrected_wrong_estimate"] == round(4 + 12 + 45 / 145 * 108, 1)
    reading = rows[("reading (LLM-judged)", "agentic")]
    assert (reading["wrong"], reading["debatable"], reading["fails_after"]) == (3, 1, "")
    assert reading["corrected_wrong_estimate"] == round(16 + 135 / 145 * 108, 1)
    overall = rows[("confirmed", "overall")]
    assert (overall["sampled"], overall["no_kept_code_edits"], overall["wrong"]) == (5, 170, 3)
    assert overall["corrected_wrong_estimate"] == round(6 + 12 + 95 / 195 * 158, 1)
    low, high = overall["corrected_ci_low_estimate"], overall["corrected_ci_high_estimate"]
    assert 18 <= low <= overall["corrected_wrong_estimate"] <= high <= 18 + 158
