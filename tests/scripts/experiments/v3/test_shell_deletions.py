import importlib.util
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
