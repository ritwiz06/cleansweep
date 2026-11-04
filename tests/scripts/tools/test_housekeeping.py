import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OLD = time.time() - 3 * 86400


def load():
    path = ROOT / "scripts" / "tools" / "housekeeping.py"
    spec = importlib.util.spec_from_file_location("housekeeping", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["housekeeping"] = module  # dataclasses look the module up there
    spec.loader.exec_module(module)
    return module


def put(path: Path, text: str | None = "x", old: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        path.mkdir()
    else:
        path.write_text(text)
    if old:
        os.utime(path, (OLD, OLD))
    return path


@pytest.fixture
def tree(tmp_path):
    """A parent folder with a repository, case studies, an archive, and a temp folder."""
    parent, temp = tmp_path / "parent", tmp_path / "temp"
    repo = parent / "cleansweep"
    repo.mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    put(repo / "table.csv", "committed\n", old=False)
    put(repo / "tool.py", "NOTES = '.notes/cited.json'\n", old=False)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "c"], cwd=repo, check=True)
    put(repo / "src" / "__pycache__" / "m.pyc")
    put(repo / ".notes" / "docs" / "PLAN.md", "see old_plan.md? no: plan.md", old=False)
    put(repo / ".notes" / "stray.md")
    put(repo / ".notes" / "cited.json")
    put(repo / ".notes" / "ui_review" / "2026-11-01" / "a.png")
    put(repo / ".notes" / "ui_review" / "2026-11-02" / "a.png")
    aside = repo / "results" / "raw" / "inject_superseded" / "sleep_x"
    put(aside / "run.json")
    os.utime(aside, (OLD, OLD))
    studies = parent / "case_studies"
    put(studies / "chain_done.sh")
    put(studies / "chain_done.log")
    put(studies / "chain_live.sh")
    put(studies / "chain_live.log")
    put(studies / "push_a.log", "push exit 0\n")
    put(studies / "backup" / "table.csv", "committed\n")
    put(studies / "backup" / "other.csv", "not committed\n")
    store = parent / "cleansweep-archive"
    put(store / "SHA256SUMS", "", old=False)
    put(temp / "cleansweep" / "ws" / "old-ws" / ".git" / "HEAD")
    os.utime(temp / "cleansweep" / "ws" / "old-ws", (OLD, OLD))
    (temp / "cleansweep" / "ws" / "new-ws" / ".git").mkdir(parents=True)
    put(temp / "cs_probe_x", None)
    put(temp / "someone_else", None)
    return parent, repo, temp, store


def args(hk, parent, repo, temp, store, *extra):
    paths = {"--parent": parent, "--repo": repo, "--temp": temp, "--archive": store}
    paths["--log"] = parent / "hk.log"
    return hk.parse([*(x for k, v in paths.items() for x in (k, str(v))), *extra])


def test_a_dry_run_lists_and_changes_nothing(tree, monkeypatch):
    hk = load()
    monkeypatch.setattr(hk.shutil, "which", lambda name: None)
    parent, repo, temp, store = tree
    busy = {"cmd:bash case_studies/chain_live.sh"}
    summary = hk.run(args(hk, *tree), busy)
    removed = {Path(p).name for p in summary["removed"]}
    assert removed == {"old-ws", "cs_probe_x", "__pycache__", "table.csv"}
    archived = sorted(a.split(" -> ")[1] for a in summary["archived"])
    assert archived == [
        "case_studies/chain_done.log",
        "case_studies/chain_done.sh",
        "case_studies/push_a.log",
        "notes/stray.md",
        "notes/ui_review/2026-11-01",
        "raw/cleansweep/results_raw/inject_superseded/sleep_x",
    ]
    assert (temp / "cs_probe_x").exists() and (parent / "case_studies" / "chain_done.sh").exists()
    assert not (parent / "hk.log").exists()


def test_apply_removes_archives_and_logs(tree, monkeypatch):
    hk = load()
    monkeypatch.setattr(hk.shutil, "which", lambda name: None)
    parent, repo, temp, store = tree
    summary = hk.run(args(hk, *tree, "--apply"), {f"{temp}/cleansweep/ws/new-ws"})
    assert summary["problems"] == []
    assert not (temp / "cs_probe_x").exists() and not (temp / "cleansweep/ws/old-ws").exists()
    assert (temp / "cleansweep/ws/new-ws").exists() and (temp / "someone_else").exists()
    assert (parent / "case_studies/backup/other.csv").exists()
    assert not (parent / "case_studies/backup/table.csv").exists()
    assert (store / "case_studies/chain_done.sh").exists()
    assert not (parent / "case_studies/chain_done.sh").exists()
    assert (store / "raw/cleansweep/results_raw/inject_superseded/sleep_x/run.json").exists()
    sums = (store / "SHA256SUMS").read_text().splitlines()
    assert "./notes/stray.md" in {line.split("  ")[1] for line in sums}
    assert (repo / ".notes/cited.json").exists() and (repo / ".notes/ui_review/2026-11-02").exists()
    assert '"applied": true' in (parent / "hk.log").read_text()


def test_a_copy_already_in_the_archive_keeps_the_original(tree, monkeypatch):
    hk = load()
    monkeypatch.setattr(hk.shutil, "which", lambda name: None)
    parent, repo, temp, store = tree
    put(store / "notes" / "stray.md", "older copy")
    summary = hk.run(args(hk, *tree, "--apply"), set())
    assert summary["problems"] == ["notes/stray.md is already in the archive"]
    assert (repo / ".notes/stray.md").exists() and (parent / "case_studies/chain_done.sh").exists()
    assert not (temp / "cs_probe_x").exists()  # removals do not wait for the archive


def test_nothing_outside_the_cleansweep_folders(tmp_path):
    hk = load()
    parent, temp = tmp_path / "p", tmp_path / "t"
    assert hk.inside(parent / "x", parent, temp)
    assert hk.inside(temp / "cleansweep" / "ws" / "w", parent, temp)
    assert hk.inside(temp / "cs_probe_1", parent, temp)
    assert not hk.inside(temp / "someone_else", parent, temp)
    assert not hk.inside(tmp_path / "elsewhere", parent, temp)
