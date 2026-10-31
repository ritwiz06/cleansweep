import subprocess

import pytest

from cleansweep.agents import clean_project
from cleansweep.agents.events import read_events

from .conftest import tree_hash

ORDER = [
    "ONBOARD",
    "BASELINE",
    "AUDIT",
    "INVESTIGATE",
    "PLAN",
    "EXECUTE",
    "FINAL_VERIFY",
    "REPORT",
    "DONE",
]


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_offline_clean_of_the_toy_repo_end_to_end(toy_repo, agent_cfg, tmp_path):
    before = tree_hash(toy_repo)
    out = tmp_path / "out"
    result = clean_project(toy_repo, agent_cfg, out=str(out), use_llm=False)
    assert tree_hash(toy_repo) == before  # the original is never written to
    summary = result["summary"]
    assert summary["verdict"] == "everything runs"
    assert summary["final"]["new_failures"] == [] and summary["files_removed"] == 3
    events = read_events(out / "events.jsonl")
    phases = [e["payload"]["to"] for e in events if e["kind"] == "phase_change"]
    assert phases == ORDER
    # one commit per kept package on the delivered branch, plus the files
    kept = [
        p
        for p in result["report"].stats["agentic"]["packages"]
        if p["status"] in ("kept", "repaired")
    ]
    log = _git(
        result["workspace"], "log", "--format=%s", f"{result['report'].stats['agentic']['branch']}"
    )
    assert len(log.splitlines()) == len(kept) + 1 and log.splitlines()[-1] == "base"
    for name in (
        "CLEANUP_REPORT.md",
        "blueprint.md",
        "PR_DESCRIPTION.md",
        "CHANGELOG_ENTRY.md",
        "report.json",
    ):
        assert (out / name).exists()
    assert len(list((out / "patches").glob("*.patch"))) == len(kept)
    status = {r.item_id: r.status for r in result["report"].results}
    by_key = {i.unit.key: status[i.item_id] for i in result["report"].plan.items}
    for key in (
        "reproduce_bug.py",
        "debug_cart.py",
        "shopcart/cart.py::os",
        "requirements.txt::requests",
    ):
        assert by_key[key] == "kept", key
    assert by_key["shopcart/storage.py::load_legacy"] == "skipped"  # security: suggest only
    # every agent and every message type took part
    agents = {(e["agent"] or "").split("#")[0] for e in events}
    assert {
        "manager",
        "explorer",
        "tester",
        "auditor",
        "investigator",
        "planner",
        "engineer",
        "validator",
        "reporter",
    } <= agents
    assert {"thought", "tool_call"} & {e["kind"] for e in events}


def test_dry_run_changes_nothing(mini, agent_cfg, tmp_path):
    before = tree_hash(mini)
    out = tmp_path / "plan"
    result = clean_project(str(mini), agent_cfg, out=str(out), dry_run=True, use_llm=False)
    assert tree_hash(mini) == before
    assert result["branch"] is None and result["summary"]["verdict"] == "nothing applied"
    assert (out / "blueprint.md").exists() and "## P1" in (out / "blueprint.md").read_text()
    workspace = result["workspace"]
    assert _git(workspace, "status", "--porcelain") == ""
    assert _git(workspace, "rev-list", "--count", "HEAD") == "1"  # only the base commit
    phases = [
        e["payload"]["to"] for e in read_events(out / "events.jsonl") if e["kind"] == "phase_change"
    ]
    assert "EXECUTE" not in phases and phases[-2:] == ["REPORT", "DONE"]


def test_out_inside_the_project_is_refused(mini, agent_cfg):
    with pytest.raises(ValueError, match="outside the project"):
        clean_project(str(mini), agent_cfg, out=str(mini / "cleanup"), use_llm=False)
    with pytest.raises(FileNotFoundError):
        clean_project(str(mini / "nope"), agent_cfg, use_llm=False)


def test_a_git_project_is_cloned_and_its_branch_applies(mini, agent_cfg, tmp_path):
    _git(mini, "init", "-q")
    _git(mini, "-c", "user.name=a", "-c", "user.email=a@a", "add", "-A")
    _git(mini, "-c", "user.name=a", "-c", "user.email=a@a", "commit", "-q", "-m", "start")
    head = _git(mini, "rev-parse", "HEAD")
    (mini / "notes.py").write_text("x = 1\n")  # uncommitted work is cleaned too
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "o"), use_llm=False)
    ws = result["workspace"]
    assert _git(ws, "merge-base", "--is-ancestor", head, result["branch"]) == ""
    assert (
        _git(mini, "rev-parse", "HEAD") == head
        and _git(mini, "branch", "--list", "cleansweep/*") == ""
    )
