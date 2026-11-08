import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_audit_miss_v3.py"
A, B, C, D = "a" * 12, "b" * 12, "c" * 12, "d" * 12


@pytest.fixture
def v3(monkeypatch):
    # load() swaps v2's audit modules for the v3 ones; put them back afterwards
    for name in ("exp_diff_audit", "exp_audit_confirm", "exp_audit_miss_v3_base"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location("exp_audit_miss_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_population_is_unsettled_no_votes_of_finished_runs(v3):
    done = {"injected v3|agentic": {"o__a-s4"}, "real v3|cleansweep": {"o__b/r1"}}
    rows = [
        {"edit": A, "method": "agentic", "source": "injected v3", "run": "o__a-s4"},
        {"edit": A, "method": "agentic", "source": "injected v3", "run": "o__a-s4"},
        {"edit": B, "method": "agentic", "source": "injected v3", "run": "o__c-s4"},
        {"edit": C, "method": "agentic", "source": "injected v3", "run": "o__a-s4"},
        {"edit": D, "method": "cleansweep", "source": "real v3", "run": "o__b/r1"},
        {"edit": A, "method": "aider", "source": "injected v3", "run": "o__a-s4"},
    ]
    audit = {A: {"answer": "no"}, B: {"answer": "no"}, C: {"answer": "no"}, D: {"answer": "no"}}
    checks = {C: {"verdict": "fine", "checked_by": "rule: injection key"}}
    assert v3.population(rows, audit, checks, done) == {
        ("agentic", "injected v3"): {A: 2},
        ("cleansweep", "real v3"): {D: 1},
    }


def test_the_audit_wrong_counts_split_confirmed_and_reading(v3):
    done = {"real v3|agentic": {"o__b/r1"}}
    rows = [
        {"edit": A, "method": "agentic", "source": "real v3", "run": "o__b/r1"},
        {"edit": B, "method": "agentic", "source": "real v3", "run": "o__b/r1"},
        {"edit": C, "method": "agentic", "source": "real v3", "run": "o__b/r2"},
    ]
    checks = {
        A: {"verdict": "wrong", "checked_by": "targeted test"},
        B: {"verdict": "wrong", "checked_by": "reading (LLM-judged)"},
        C: {"verdict": "wrong", "checked_by": "targeted test"},
    }
    assert v3.audit_wrong(rows, checks, done, {"targeted test"}) == {"agentic": (1, 1)}


def test_the_sampler_reads_the_v3_audit_and_writes_its_own_files(v3, tmp_path):
    miss = v3.load([tmp_path])
    assert miss.AUDIT == ROOT / "results" / "raw" / "diff_audit_v3"
    assert miss.TESTS == ROOT / "results" / "raw" / "audit_miss_v3" / "tests"
    assert miss.PER_METHOD == 50 and set(miss.METHODS) == {"agentic", "cleansweep"}
    assert miss.collect() == ({}, [])
    report = tmp_path / "real_v3" / "o__b" / "agentic-r1" / "report.json"
    assert miss.confirm.opened("aidev:o/b@v1", report)[1]["aidev_clones"] == (
        "data/raw/aidev/heldout"
    )
