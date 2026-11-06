import json
import subprocess

from cleansweep.agents.listing import NAME, project_files, save_project_files

from .conftest import write_project


def test_files_git_lists_with_their_line_counts(tmp_path):
    root = write_project(
        tmp_path / "proj",
        {"a.py": "x = 1\ny = 2\n", "pkg/b.py": "z = 3", "logo.png": "", ".gitignore": "*.log\n"},
    )
    (root / "logo.png").write_bytes(b"\x89PNG\0\0")
    (root / "run.log").write_text("ignored\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    files = {f["path"]: f["lines"] for f in project_files(root)}
    assert files == {".gitignore": 1, "a.py": 2, "pkg/b.py": 1, "logo.png": None}
    save_project_files(root, tmp_path / "out")
    saved = json.loads((tmp_path / "out" / NAME).read_text())
    assert [f["path"] for f in saved["files"]] == sorted(files)


def test_a_folder_git_cannot_list_writes_nothing(tmp_path):
    save_project_files(tmp_path / "missing", tmp_path / "out")
    assert not (tmp_path / "out" / NAME).exists()
