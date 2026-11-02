import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from cleansweep.core.io import save_json
from cleansweep.core.models import (
    CleanupItem,
    CleanupPlan,
    CodeUnit,
    DiffOutcome,
    EditResult,
    SweepReport,
)

ROOT = Path(__file__).resolve().parents[4]
FOLDER = ROOT / "scripts" / "experiments" / "v2"


def load(name):
    sys.path.insert(0, str(FOLDER))
    spec = importlib.util.spec_from_file_location(name, FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_repo(tmp_path) -> tuple[Path, str]:
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "m.py").write_text(
        "def total(x):\n    return x\n\n\ndef legacy(y):\n    return y\n"
    )
    (repo / "README.md").write_text("Call total().\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=repo, check=True)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return repo, rev.stdout.strip()


def dead_item(reason: str) -> CleanupItem:
    return CleanupItem(
        "i1",
        CodeUnit("pkg/m.py", "function", "legacy", 5, 6),
        "dead_code",
        "delete_unit",
        "safe",
        reason,
        evidence=[
            "vulture: unused function (60% confidence)",
            "R1: no callers found, so it is safe to delete",
            "knowledge base: 80% of mined maintainer removal requests are dead_code",
            "used outside its file, so not rewritten automatically",
        ],
        sources=["vulture", "investigator", "thorough"],
    )


def test_the_view_shows_code_and_facts_but_never_the_verdict(tmp_path):
    review = load("exp_llm_review")
    repo, rev = git_repo(tmp_path)
    item = dead_item("Investigator (safe): delete it, thorough mode applied it")
    result = EditResult(
        "i1", "rolled_back", diff_check=DiffOutcome(False, 4), notes="probes found a change"
    )
    text = review.view(item, result, repo, rev, "proj")
    assert "def legacy(y):" in text and "Delete `legacy` from `pkg/m.py`." in text
    assert "vulture: unused function" in text and "appears in no other file" in text
    assert "4 cases, results changed" in text and "A check on the change failed" in text
    for hidden in ("Investigator", "R1:", "safe", "thorough", "knowledge base", "automatically"):
        assert hidden not in text, hidden


def test_votes_and_agreement():
    review = load("exp_llm_review")
    assert review.majority(["accept", "reject", "accept"]) == "accept"
    assert review.majority(["accept", "reject", "unsure"]) == "unsure"
    labels = ("accept", "reject", "unsure")
    assert review.fleiss([["accept"] * 3, ["reject"] * 3], labels) == 1.0
    assert review.cohen(["accept", "reject"], ["accept", "reject"]) == 1.0
    assert review.cohen(["accept", "reject"], ["reject", "accept"]) == -1.0


def test_sheet_keeps_a_persons_decisions_and_scores_both_columns(tmp_path, monkeypatch):
    sheet = load("exp_review_sheet")
    monkeypatch.setattr(sheet, "CASES", tmp_path)
    item = dead_item("Investigator (suggest): a person should decide")
    item.lane, item.action, item.sources = "suggest", "report_only", ["vulture"]
    plan = CleanupPlan("local:proj", "t", [item])
    report = SweepReport("local:proj", "agentic", "now", 0, "t", "t", plan, results=[])
    (tmp_path / "proj-safe").mkdir()
    save_json(report, tmp_path / "proj-safe" / "report.json")
    path = sheet.write_sheet("proj", "proj-safe", None)
    text = path.read_text()
    assert "LLM-reviewer acceptance (independent model, blinded)" in text
    path.write_text(text.replace("| - |  |  |  |  |  |", "| - |  |  |  | reject | keep it |"))
    reviews = {1: {"decision": "accept", "votes": ["accept", "accept", "unsure"], "reason": "dead"}}
    sheet.write_sheet("proj", "proj-safe", None, reviews)
    row = next(line for line in path.read_text().splitlines() if line.startswith("| 1 |"))
    assert "| accept | accept, accept, unsure | dead | reject | keep it |" in row
    scores = sheet.score("proj").read_text().splitlines()
    assert scores[1].startswith("dead_code,safe suggestion,1,1,0,0,0,1.0,0,1,0,0,0.0")
    assert json.loads((tmp_path / "proj" / "review_rows.json").read_text())["rows"][0]["n"] == 1


def test_mining_items_and_calibration_kappa(tmp_path, monkeypatch):
    review = load("exp_llm_review")
    monkeypatch.setattr(review, "NOTES", tmp_path)
    (tmp_path / "mining_check.md").write_text(
        "# Removal-request check\n\n"
        "## 1. org/repo PR #3 — `pkg/a.py` (comment 11)\n\n> Let's remove this helper\n\n"
        "- LLM: removal = True, category = dead_code, target = helper\n- **Your label:** yes\n\n"
        "## 2. org/repo PR #4 — `pkg/b.py` (comment 12)\n\n> Looks good\n\n"
        "- LLM: removal = False, category = -, target = -\n- **Your label:** \n"
    )
    items = review._mining_items()
    assert [(i["n"], i["extracted"], i["human"]) for i in items] == [
        (1, True, "yes"),
        (2, False, ""),
    ]
    assert items[0]["comment"] == "Let's remove this helper" and items[0]["path"] == "pkg/a.py"
    report = tmp_path / "report"
    report.mkdir()
    key = [{"id": "C1", "llm": "accept"}, {"id": "C2", "llm": "reject"}]
    (report / "calibration_key.json").write_text(json.dumps(key))
    (report / "calibration_sheet.md").write_text(
        "## C1\n\nview\n\n**Your decision:** \n\n## C2\n\nview\n\n**Your decision:** \n"
    )
    assert review.kappa()["status"].startswith("not checked by a human")
    (report / "calibration_sheet.md").write_text(
        "## C1\n\nview\n\n**Your decision:** accept\n\n## C2\n\nview\n\n**Your decision:** reject\n"
    )
    assert review.kappa() == {"labeled": 2, "of": 2, "agreement": 1.0, "cohen_kappa": 1.0}


def test_a_long_sheet_is_sampled_across_categories():
    review = load("exp_llm_review")
    rows = [{"n": 1, "kind": "applied", "category": "dead_code"}]
    rows += [{"n": n, "kind": "suggestion", "category": "security"} for n in range(2, 32)]
    rows += [{"n": n, "kind": "suggestion", "category": "duplicate"} for n in range(32, 36)]
    picked = review.pick_rows(rows, limit=10)
    assert picked[0]["n"] == 1 and len(picked) == 11
    cats = [r["category"] for r in picked[1:]]
    assert cats.count("duplicate") == 4 and cats.count("security") == 6
    assert review.pick_rows(rows, limit=10) == picked  # fixed seed
    assert len(review.pick_rows(rows, limit=50)) == len(rows)
