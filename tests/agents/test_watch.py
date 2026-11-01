"""Watch mode: the decision rule, a live watch over a small repository, the simulated watch."""

import json
import subprocess

from cleansweep.agents import clean_project, watch
from cleansweep.core.models import CommitEvent

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
CODE = "def total(prices):\n    return sum(prices)\n"
TEST = "from shop.core import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"


def _commit(repo, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", message], cwd=repo, check=True)


def _state(**kw) -> dict:
    base = {"open_items": 2, "slop_loc": 2, "loc": 1000, "new_items": 0, "commits_since_clean": 1}
    return {**base, **kw}


def test_the_rule_cleans_when_slop_is_worth_it_and_the_budget_allows():
    assert watch.decide(_state(open_items=0, slop_loc=0)) == ("wait", "no slop is open")
    decision, reason = watch.decide(_state(slop_loc=50))
    assert decision == "clean" and reason.startswith("slop is 5.0% of the Python lines")
    decision, reason = watch.decide(_state(slop_loc=50, budget_tests=10, test_runs_used=6))
    assert (
        decision == "wait"
        and reason.startswith("the test budget is used up")
        and "4 of 10" in reason
    )
    decision, reason = watch.decide(_state(open_items=9, slop_loc=50, budget_tests=5))
    assert decision == "clean" and reason.endswith("the budget left covers 4 of the 9 items")
    assert watch.decide(_state(new_items=3))[0] == "clean"
    assert watch.decide(_state(commits_since_clean=20))[0] == "clean"
    decision, reason = watch.decide(_state())
    assert decision == "wait" and "0.2% of the Python lines" in reason


def test_a_watch_logs_every_decision_and_cleans_a_copy(tmp_path, agent_cfg):
    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run([*GIT, "init", "-q"], cwd=repo, check=True)
    _commit(repo, {"shop/__init__.py": "", "shop/core.py": CODE, "tests/test_core.py": TEST}, "a")
    runs = []

    def clean(snapshot, out, test_runs):
        runs.append((out, test_runs))
        return clean_project(snapshot, agent_cfg, out=out, use_llm=False)

    w = watch.Watch(str(repo), str(tmp_path / "watch"), budget_tests=40)
    first = w.poll(clean)
    assert first["decision"] == "wait" and first["reason"] == "no slop is open"
    assert w.poll(clean) is None  # no new commit
    leftover = "import os\n\n\ndef old_total(prices):\n    return 0\n"
    _commit(repo, {"debug_old.py": leftover, "shop/core.py": "import json\n" + CODE}, "feature")
    second = w.poll(clean)
    assert second["decision"] == "clean" and second["slop"]["items"] >= 2
    assert second["run"] == "clean-001" and second["outcome"]["verdict"] == "everything runs"
    assert second["test_runs_used"] == second["outcome"]["test_runs"] > 0
    assert (repo / "debug_old.py").exists()  # the original is never changed
    assert runs == [(str(tmp_path / "watch" / "clean-001"), 40)]  # capped at the budget left
    _commit(repo, {"README.md": "shop\n"}, "docs")
    third = w.poll(clean)
    assert third["decision"] == "wait" and third["slop"]["items"] == 0  # delivered, awaiting merge
    log = [
        json.loads(line)
        for line in (tmp_path / "watch" / "watch_log.jsonl").read_text().splitlines()
    ]
    assert [e["decision"] for e in log] == ["wait", "clean", "wait"] and all(
        e["reason"] for e in log
    )
    resumed = watch.Watch(str(repo), str(tmp_path / "watch"), budget_tests=40)
    assert resumed.state["cleans"] == 1 and resumed.poll(clean) is None


def test_the_simulated_watch_replays_a_history(monkeypatch):
    history = [CommitEvent(f"c{i}", f"2026-01-0{i + 1}T00:00:00Z", False) for i in range(4)]
    snaps = {
        0: {"items": {}, "loc": 100, "files": []},
        2: {"items": {"a": ["dead_code", "m.py::f", 3]}, "loc": 100, "files": []},
        3: {"items": {"a": ["dead_code", "m.py::f", 3], "b": ["unused_import", "m.py::os", 1]}},
    }
    snaps[3]["loc"], snaps[3]["files"] = 100, []
    monkeypatch.setattr("cleansweep.scheduler.replay.snapshots", lambda *a, **k: snaps)
    result = watch.simulate_watch(history, "repo", budget_tests=0)
    assert [d["decision"] for d in result["decisions"]] == ["wait", "wait", "clean", "wait"]
    assert result["sweeps"] == 1 and result["test_runs_est"] == watch.clean_cost(1)
    assert result["final_slop"] == 1 and result["slop_debt"] == 1
