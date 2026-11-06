import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "shell_deletions.py"


def load():
    spec = importlib.util.spec_from_file_location("shell_deletions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_plain_deletions_of_existing_workspace_paths_run(tmp_path):
    deletions = load()
    root = tmp_path / "repo"
    for name in ("pkg/old.py", "debug.py", "build/out.txt", "keep.py", "folder/a.py", ".git/HEAD"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x\n")
    commands = [
        "rm pkg/old.py debug.py && echo done",
        "git rm -r build; mv keep.py kept.py",
        "rm -rf /etc/hosts\nrm ../outside.py\nrm *.py\nrm missing.py\nrm -r .git",
        "rm folder\nrm --cached keep.py\ncat keep.py | rm keep.py\nrm -r .",
    ]
    out = deletions.run_deletions(commands, root)
    assert out["executed"] == ["rm pkg/old.py debug.py", "git rm -r build"]
    reasons = {r["command"]: r["reason"] for r in out["refused"]}
    assert reasons["echo done"] == reasons["mv keep.py kept.py"] == "not a deletion"
    assert reasons["rm -rf /etc/hosts"].startswith("not a plain relative path")
    assert reasons["rm ../outside.py"].startswith("not a plain relative path")
    assert reasons["rm *.py"].startswith("not a plain relative path")
    assert reasons["rm missing.py"].startswith("not in the workspace")
    assert reasons["rm -r .git"].startswith("not a plain relative path")
    assert reasons["rm folder"].startswith("a folder without -r")
    assert reasons["rm --cached keep.py"] == "a flag other than -r or -f"
    assert reasons["cat keep.py | rm keep.py"] == "not a deletion"
    assert reasons["rm -r ."].startswith("not a plain relative path")
    left = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert left == [".git/HEAD", "folder/a.py", "keep.py"]


def test_files_left_empty_are_deleted_unless_they_were_empty_at_base(tmp_path):
    deletions = load()
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    files = {"pkg/old.py": "x = 1\n", "kept.py": "y = 2\n", "pkg/__init__.py": ""}
    for name, text in files.items():
        (root / name).write_text(text)
    git = ["git", "-c", "user.name=agent_a", "-c", "user.email=agent_a@example.com"]
    subprocess.run([*git, "init", "-q"], cwd=root, check=True)
    subprocess.run([*git, "add", "-A"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=root, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    (root / "pkg" / "old.py").write_text("  \n\n")
    (root / "kept.py").write_text("y = 3\n")
    (root / "new.py").write_text("")
    assert deletions.delete_emptied(root, base) == ["pkg/old.py"]
    assert not (root / "pkg" / "old.py").exists()
    assert (root / "pkg" / "__init__.py").exists() and (root / "new.py").exists()
