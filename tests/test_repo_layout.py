import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "docs" / "repo_layout.md"
SCRATCH = ["tmp_*", "*_old", "*_old.*", "*_backup*", "scratch*", "*.bak", "untitled*", "debug_*"]
# tracked files the layout rules would flag, each with the reason it stays
ALLOWED = {
    ".gitignore": "git's own file",
}
ALLOWED_PATTERNS = {
    "demo/shop_app/*": "the demo app's planted slop (inventory_old.py, scratch_restock.py)",
    "tests/fixtures/*": "fixture projects with planted slop (debug_cart.py, *_old.py)",
}


def layout() -> tuple[set[str], set[str]]:
    """(files, folders) the tree in docs/repo_layout.md lists, as paths from the repo root."""
    files, folders, parents = set(), set(), {}
    block = LAYOUT.read_text().split("```")[1]
    for line in block.splitlines()[2:]:
        m = re.match(r"^([│ ]*)[├└]── (.+?)(?:\s{2,}.*)?$", line)
        if not m:
            continue
        depth = len(m.group(1)) // 4
        base = parents[depth - 1] if depth else ""
        for name in m.group(2).split(", "):
            path = f"{base}/{name}" if base else name
            (folders if name.endswith("/") else files).add(path.rstrip("/"))
            if name.endswith("/"):
                parents[depth] = path.rstrip("/")
    return files, folders


def placed(path: str, files: set[str], folders: set[str]) -> bool:
    """A listed file, a file directly in a listed folder, or below a folder the tree does not
    divide further; tests/ mirrors the package."""
    if path in files:
        return True
    parts = path.split("/")
    if parts[0] == "tests" and len(parts) > 2 and parts[1] not in ("app", "scripts", "fixtures"):
        return (ROOT / "src" / "cleansweep" / parts[1]).is_dir()
    for i in range(len(parts) - 1, 0, -1):
        folder = "/".join(parts[:i])
        if folder in folders:
            divided = any(f.startswith(folder + "/") for f in folders)
            return i == len(parts) - 1 or not divided
    return False


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def allowed(path: str) -> bool:
    return path in ALLOWED or any(fnmatch.fnmatch(path, p) for p in ALLOWED_PATTERNS)


def test_every_tracked_file_sits_where_the_layout_says():
    files, folders = layout()
    stray = [p for p in tracked() if not placed(p, files, folders) and not allowed(p)]
    assert stray == [], "not in docs/repo_layout.md: " + ", ".join(stray[:20])


def test_no_tracked_file_looks_like_scratch():
    named = [p for p in tracked() if any(fnmatch.fnmatch(Path(p).name, s) for s in SCRATCH)]
    assert [p for p in named if not allowed(p)] == []


def test_the_layout_tree_is_read():
    files, folders = layout()
    assert {"README.md", "scripts/reproduce_tables.sh"} <= files
    assert {"src/cleansweep/agents", "scripts/experiments/v2", "results/summary/v2"} <= folders
