import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_tables_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_tables_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def plants(removed: int, total: int = 7, trap: int = 0) -> dict:
    slop = [
        {"kind": "slop", "category": "dead_code", "removed": int(i < removed)} for i in range(total)
    ]
    return {"inject": {"plants": [*slop, {"kind": "trap", "category": "x", "removed": trap}]}}


def test_a_timed_out_run_stays_in_the_denominator_with_nothing_removed():
    tables = load()
    records = {
        ("a-s4", "agentic"): {**plants(7), "llm_calls": 10, "minutes": 5},
        ("b-s4", "agentic"): {"timed_out": "time cap"},
        ("a-s4", "cleansweep"): {"timed_out": "time cap", "capped": "x"},
    }
    rows = {r["method"]: r for r in tables.injection_table(records, ["a-s4", "b-s4", "c-s4"])}
    team = rows["agentic"]
    assert (team["finished"], team["timed_out"], team[tables.NOT_RUN]) == (1, 1, 1)
    assert team["recall"] == 0.5  # 7 of 14: the timed-out run's 7 count as not removed
    assert rows["cleansweep"]["recall"] == 0.0 and rows["aider"][tables.NOT_RUN] == 3


def test_hypotheses_follow_the_preregistered_rules():
    tables = load()
    inject = {
        (f"r{i}-s4", m): {"llm_calls": calls, **plants(5)}
        for i in range(6)
        for m, calls in (("agentic", 100), ("agentic-no_resolver", 100), ("agentic-batch", 50))
    }
    cells = {}
    for i in range(6):
        cells[("injected v3", "agentic", f"r{i}-s4")] = {
            "edits": 10,
            "wrong": 0,
            "wrong_confirmed": 0,
        }
        cells[("injected v3", "agentic-no_resolver", f"r{i}-s4")] = {
            "edits": 10,
            "wrong": 2,
            "wrong_confirmed": 1,
        }
        cells[("injected v3", "agentic-batch", f"r{i}-s4")] = {
            "edits": 10,
            "wrong": 0,
            "wrong_confirmed": 0,
        }
    finished = tables.finished_runs(inject, {})
    autonomy = [{"pass": 1, "completed": i < 27} for i in range(30)]
    out = {h["hypothesis"]: h for h in tables.hypotheses(cells, finished, inject, {}, autonomy)}
    assert out["H1"]["result"] == tables.NOT_RUN  # no REAL runs yet
    assert out["H2"]["result"] == "supported"  # 0 against 12, Wilcoxon p = 0.03
    assert out["H3"]["result"] == "supported" and "ratio 0.500" in out["H3"]["evidence"]
    assert out["H4"]["result"] == "supported" and "27 of 30" in out["H4"]["evidence"]
    autonomy[26]["completed"] = False
    out = {h["hypothesis"]: h for h in tables.hypotheses(cells, finished, inject, {}, autonomy)}
    assert out["H4"]["result"] == "not supported"


def test_ratio_ci_brackets_the_pooled_ratio():
    tables = load()
    point, low, high = tables.ratio_ci([(1, 10), (3, 10), (2, 10)])
    assert point == 0.2 and low <= 0.2 <= high


def test_sets_and_autonomy_are_read_from_every_raw_folder(tmp_path):
    import json

    tables = load()
    real_raw, inject_raw, auto_raw = (tmp_path / n for n in ("real", "inject", "auto"))
    (inject_raw / "inject_v3").mkdir(parents=True)
    (inject_raw / "inject_v3" / "set.json").write_text(json.dumps({"set": ["r/far", "o/b"]}))
    (real_raw / "real_v3").mkdir(parents=True)
    (real_raw / "real_v3" / "set.json").write_text(json.dumps({"set": ["r/front"]}))
    result = auto_raw / "autonomy" / "o__x" / "pass1"
    result.mkdir(parents=True)
    (result / "result.json").write_text(json.dumps({"repo": "o/x", "pass": 1}))
    raws = [real_raw, inject_raw, auto_raw]
    assert tables.planned_set(raws, "inject_v3", ["o/a", "o/b"]) == ["r/far", "o/b"]
    assert tables.planned_set(raws, "real_v3", ["o/c"]) == ["r/front"]
    assert tables.planned_set([auto_raw], "real_v3", ["o/c"]) == ["o/c"]
    assert [r["repo"] for r in tables.autonomy_records(raws)] == ["o/x"]


def test_second_model_and_curve_use_only_the_first_five_projects():
    tables = load()
    repos = [f"r{i}-s4" for i in range(6)]
    inject = {(r, "agentic"): plants(5) for r in repos}
    inject.update({(r, "agentic-m2"): plants(3, trap=1) for r in repos[:5]})
    real = {(f"p{i}", m): {"lines_removed": 10} for i in range(6) for m in ("agentic", "aider")}
    real[("p0", "agentic-thorough")] = {"lines_removed": 4}
    cells = {("real v3", "agentic-thorough", "p0/r1"): {"edits": 2, "wrong": 1}}
    rows = tables.second_model_table(inject, real, cells, repos[:5], ["p0", "p1"])
    by = {(r["set"], r["method"]): r for r in rows}
    team, m2 = by[("injected v3", "agentic")], by[("injected v3", "agentic-m2")]
    assert (team["finished"], team["slop_removed (INJECT)"]) == (5, 25)
    assert (m2["slop_removed (INJECT)"], m2["traps_removed (INJECT)"]) == (15, 5)
    assert by[("real v3", "agentic-m2")][tables.NOT_RUN] == 2
    assert by[("real v3", "agentic")]["slop_removed (INJECT)"] == ""
    curve = {r["method"]: r for r in tables.curve_table(real, cells, ["p0", "p1"])}
    assert curve["agentic"]["lines_removed"] == 20  # p2-p5 are outside the curve's projects
    thorough = curve["agentic-thorough"]
    assert (thorough["finished"], thorough["wrong_all_tiers (incl. LLM-judged readings)"]) == (1, 1)


def test_a_replayed_rerun_takes_its_first_attempts_cost(tmp_path):
    import json

    tables = load()
    folder = tmp_path / "real_v3" / "xgboosted__pandas-ta-classic" / "agentic-no_research-r1"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps({"minutes": 9.81, "llm_requests": 6}))
    record = tables.real_records([tmp_path])[
        ("xgboosted__pandas-ta-classic", "agentic-no_research")
    ]
    assert (record["minutes"], record["llm_requests"]) == (71.15, 7)


def test_the_sets_table_names_each_replacement_without_local_paths(tmp_path):
    import json

    tables = load()
    (tmp_path / "inject_v3").mkdir()
    replaced = {"replaced": "o/bad", "reason": "/home/x/o__bad: too few modules", "by": "r/far"}
    settled = {"set": ["o/a", "r/far"], "replacements": [replaced]}
    (tmp_path / "inject_v3" / "set.json").write_text(json.dumps(settled))
    split = {"inject": [], "real": [{"full_name": "o/c"}]}
    rows = tables.sets_table([tmp_path], split)
    assert [(r["set"], r["repo"], r["replaces"], r["reason"]) for r in rows] == [
        ("INJECT", "o/a", "", ""),
        ("INJECT", "r/far", "o/bad", "too few modules"),
        ("REAL", "o/c", "", ""),
    ]


def test_the_audit_table_counts_finished_runs_even_when_they_kept_nothing():
    tables = load()
    real = {("p", "aider"): {}, ("q", "aider"): {"timed_out": "time cap"}, ("p", "agentic"): {}}
    cells = {
        ("real v3", "agentic", "p/r1"): {
            "edits": 4,
            "wrong": 1,
            "wrong_confirmed": 0,
            "debatable": 0,
        }
    }
    rows = tables.audit_table(cells, tables.finished_runs({}, real))
    aider = next(r for r in rows if r["set"] == "real v3" and r["method"] == "aider")
    assert (aider["runs"], aider["kept_code_edits"]) == (1, 0)
