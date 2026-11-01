import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v1"

DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
index 1111111..2222222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,6 +1,3 @@
-import sys
 import os
-def helper(n):
-    return n
 def main():
     return os.sep
diff --git a/scratch.py b/scratch.py
deleted file mode 100644
index 3333333..0000000
--- a/scratch.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("hi")
-print("bye")
diff --git a/tests/test_mod.py b/tests/test_mod.py
index 4444444..5555555 100644
--- a/tests/test_mod.py
+++ b/tests/test_mod.py
@@ -1 +1 @@
-x = 1
+x = 2
"""


def load(name):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diff_files_reads_status_lines_and_removed_defs():
    files = {f["path"]: f for f in load("exp_oneshot_breakages").diff_files(DIFF)}
    assert files["pkg/mod.py"]["status"] == "modified"
    assert files["pkg/mod.py"]["removed"] == 3
    assert files["pkg/mod.py"]["removed_defs"] == ["helper"]
    assert files["scratch.py"]["status"] == "deleted"
    assert files["scratch.py"]["removed"] == 2


def test_edit_types_split_deletions_from_source_edits():
    kinds = load("exp_oneshot_breakages").edit_types(DIFF)
    assert kinds["files_deleted"] == 1
    assert kinds["lines_in_deleted_files"] == 2
    assert kinds["source_files_edited"] == 1
    assert kinds["other_files_edited"] == 1  # the test file


def test_cause_prefers_used_deletions_then_syntax_then_names():
    cause = load("exp_oneshot_breakages").cause
    assert cause({"deleted_files_used": ["a.py"], "syntax_error_files": ["b.py"]})[0].startswith(
        "deleted"
    )
    assert "does not parse" in cause({"syntax_error_files": ["b.py"]})[1]
    assert "undefined: sys" in cause({"new_undefined_names": ["sys"]})[1]
    assert cause({})[1] == "changed logic"


def test_touched_units_skip_tests():
    units = load("exp_guard_on_oneshot").touched_units(DIFF)
    assert sorted(u.path for u in units) == ["pkg/mod.py", "scratch.py"]


def test_summary_counts_blocks_and_false_alarms(tmp_path, monkeypatch):
    module = load("exp_guard_on_oneshot")
    monkeypatch.setattr(module, "SUMMARY", tmp_path / "guard_on_oneshot")
    base = {"target_set": "swebench_t2", "edits_applied": 1, "applied": True}
    rows = [
        base | {"target": "a", "hidden_changed": 1, "blocked": True, "check": "compile"},
        base | {"target": "b", "hidden_changed": 1, "blocked": True, "check": "probes"},
        base | {"target": "c", "hidden_changed": 1, "blocked": False, "check": None},
        base | {"target": "d", "hidden_changed": 0, "blocked": True, "check": "tests"},
        base | {"target": "e", "hidden_changed": 0, "blocked": False, "check": None},
    ]
    module.write_summary(rows)
    md = (tmp_path / "guard_on_oneshot.md").read_text()
    assert "| swebench_t2 | 5 | 2/3 | 1 | 0 | 1 | 1/2 |" in md


def test_compile_failures_name_the_files_that_do_not_compile():
    oneshot = load("exp_oneshot_compile")
    files = {"a.py": "x = 1\n", "b.py": 'x = 1\n"', "notes.md": '"'}
    assert [f.split(":")[0] for f in oneshot.compile_failures(files)] == ["b.py"]


def test_rewritten_files_apply_the_diff_at_the_sha(tmp_path):
    import subprocess

    oneshot = load("exp_oneshot_compile")

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout

    git("init", "-q")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "import sys\nimport os\ndef helper(n):\n    return n\ndef main():\n    return os.sep\n"
    )
    (tmp_path / "scratch.py").write_text('print("hi")\nprint("bye")\n')
    git("add", "-A")
    git("-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "base")
    sha = git("rev-parse", "HEAD").strip()
    (tmp_path / "pkg" / "mod.py").write_text("x")  # the working tree doesn't matter
    files = oneshot.rewritten_files(tmp_path, sha, DIFF.split("diff --git a/tests")[0])
    assert files == {"pkg/mod.py": "import os\ndef main():\n    return os.sep\n"}
