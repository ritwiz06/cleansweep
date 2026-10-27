import subprocess

import pandas as pd

from cleansweep.core.models import RepoRef
from cleansweep.data import aidev


def test_full_name_and_pr_references():
    assert aidev.full_name("https://api.github.com/repos/o/n") == "o/n"
    assert aidev.full_name("https://github.com/o/n/") == "o/n"
    m = aidev.PR_REF.search("fix the parser (#123)")
    assert int(m.group(1)) == 123
    m = aidev.PR_REF.search("Merge pull request #45 from o/branch\n\nbody")
    assert int(m.group(2)) == 45


def test_candidates_filters_and_samples(monkeypatch):
    repos = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "full_name": ["o/a", "o/b", "o/c", "o/d"],
            "language": ["Python", "Python", "Go", "Python"],
            "is_forked": [False, False, False, True],
            "stars": [10, 20, 30, 40],
        }
    )
    prs = pd.DataFrame(
        {
            "id": range(25),
            "agent": "agent_a",
            "merged_at": "2026-01-01",
            "repo_id": [1] * 12 + [2] * 5 + [3] * 8,
        }
    )
    tables = {"repository": repos, "pull_request": prs}
    monkeypatch.setattr(aidev, "table", lambda name, cols=None: tables[name])
    out = aidev.candidates({"min_agent_prs": 10, "max_candidates": 5, "seed": 0})
    assert list(out.full_name) == ["o/a"]  # o/b has 5, o/c is Go, o/d is a fork
    assert out.clone_url[0] == "https://github.com/o/a.git"


def test_history_marks_agent_pull_requests(tmp_path, monkeypatch):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    repo = tmp_path / "o__n"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for i, msg in enumerate(["start", "add parser (#7)", "human fix (#8)"]):
        (repo / f"f{i}.py").write_text("x = 1\n")
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*git, "commit", "-q", "-m", msg], cwd=repo, check=True)
    monkeypatch.setattr(aidev, "_agent_prs", lambda name: ({7: "agent_a"}, {}))
    monkeypatch.setattr(
        aidev,
        "_cfg",
        lambda: {
            "history_commits": 300,
            "history_cache": str(tmp_path / "cache"),
            "clones": str(tmp_path),
        },
    )
    events = aidev.load_history(RepoRef("aidev:o/n", "u", str(repo)))
    assert [e.pr_number for e in events] == [None, 7, 8]
    assert [e.is_agent for e in events] == [False, True, False]
    assert events[1].agent == "agent_a" and events[1].files == ["f1.py"]
    assert (tmp_path / "cache" / "o__n.json").exists()
