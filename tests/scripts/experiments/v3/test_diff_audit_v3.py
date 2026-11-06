import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_diff_audit_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_diff_audit_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report(path: Path, repo_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"repo_id": repo_id, "plan": {"items": []}, "results": []}))


def test_runs_cover_finished_v3_runs_only(tmp_path):
    audit = load()
    raw = tmp_path / "raw"
    _report(raw / "inject_v3" / "o__a-s4" / "agentic.json", "aidev:o/a@p1")
    (raw / "inject_v3" / "o__a-s4" / "key.json").write_text("{}")
    capped = raw / "inject_v3" / "o__a-s4" / "cleansweep.json"
    capped.write_text(json.dumps({"method": "cleansweep", "stats": {"timed_out": "time cap"}}))
    _report(raw / "real_v3" / "o__b" / "aider-r1" / "report.json", "aidev:o/b@v1")
    _report(raw / "inject" / "o__c-s1" / "agentic.json", "aidev:o/c@x")  # v2's: never
    runs = audit.runs_in([raw])
    assert [(s, m, r) for s, m, r, _ in runs] == [
        ("injected v3", "agentic", "o__a-s4"),
        ("real v3", "aider", "o__b/r1"),
    ]


def test_trees_are_the_injected_and_held_out_clones_at_the_run_commit(tmp_path):
    audit = load()
    v2 = audit.load_v2([tmp_path])
    inject = tmp_path / "inject_v3" / "o__a-s4" / "agentic.json"
    tree = v2.tree_for("aidev:o/a@p1", inject)
    assert tree.repo == ROOT / "data" / "raw" / "aidev" / "injected" / "o__a" and tree.rev == "p1"
    real = tmp_path / "real_v3" / "o__b" / "agentic-r1" / "report.json"
    tree = v2.tree_for("aidev:o/b@v1", real)
    assert tree.repo == ROOT / "data" / "raw" / "aidev" / "heldout" / "o__b" and tree.rev == "v1"
    assert v2.OUT == ROOT / "results" / "raw" / "diff_audit_v3"
    assert v2.CHECKS == ROOT / "results" / "summary" / "v3" / "diff_audit_checks.csv"


def test_the_injection_key_settles_every_kept_edit_even_a_no_vote(tmp_path, monkeypatch):
    audit = load()
    v2 = audit.load_v2([tmp_path])
    monkeypatch.setattr(v2, "OUT", tmp_path / "out")
    monkeypatch.setattr(v2, "CHECKS", tmp_path / "checks.csv")
    monkeypatch.setattr(v2, "SUMMARY", tmp_path)
    run = tmp_path / "inject_v3" / "o__a-s4"
    run.mkdir(parents=True)
    (run / "key.json").write_text("{}")
    report = str(run / "agentic.json")
    (tmp_path / "out").mkdir()
    records = {
        "e1": {"answer": "no", "diff": "trap", "report": report},
        "e2": {"answer": "yes", "diff": "slop", "report": report},
        "e3": {"answer": "no", "diff": "other", "report": report},
    }
    (tmp_path / "out" / "audit.json").write_text(json.dumps(records))
    monkeypatch.setattr(v2, "plant_lines", lambda key: ({"slop"}, {"trap"}))
    rule = {"trap": "wrong", "slop": "fine"}
    monkeypatch.setattr(v2, "plant_rule", lambda diff, slop, traps: rule.get(diff, ""))
    monkeypatch.setattr(v2, "trap_kind", lambda diff: "framework callback")
    assert audit.auto(v2) == 2
    checks = v2.checks()
    assert (
        checks["e1"]["verdict"] == "wrong" and checks["e1"]["checked_by"] == "rule: injection key"
    )
    assert checks["e2"]["verdict"] == "fine" and "e3" not in checks
