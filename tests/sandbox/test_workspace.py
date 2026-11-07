import subprocess

from cleansweep.sandbox.workspace import GIT_ID, Workspace

UNIT = (
    "import unittest\n\n\nclass T(unittest.TestCase):\n"
    "    def test_ok(self):\n        self.assertEqual(1, 1)\n\n"
    "    def test_bad(self):\n        self.assertEqual(1, 2)\n\n"
    "    def test_parts(self):\n        for n in (1, 2):\n"
    "            with self.subTest(n=n):\n                self.assertEqual(n, 1)\n"
)


def _workspace(root, files: dict[str, str]) -> Workspace:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", *GIT_ID, "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", *GIT_ID, "commit", "-qm", "base"], cwd=root, check=True)
    return Workspace(root, "local:t")


def test_a_unittest_suite_gives_per_test_statuses(tmp_path):
    ws = _workspace(tmp_path, {"tests/test_unit.py": UNIT})
    ws.test_command = {"runner": "unittest", "start": "tests", "top": "tests"}
    result = ws.run_tests()
    assert (result.passed, result.failed) == (1, 2) and ws.test_runs == 1
    assert ws.last_statuses == {
        "tests.test_unit.T::test_ok": "passed",
        "tests.test_unit.T::test_bad": "failed",
        "tests.test_unit.T::test_parts": "failed",
    }
    ws.run_tests(["tests/test_unit.py"])  # a file runs as its module
    assert len(ws.last_statuses) == 3


def test_a_plain_command_is_one_result(tmp_path):
    ws = _workspace(tmp_path, {"Makefile": "test:\n\texit 3\n"})
    ws.test_command = {"runner": "command", "argv": ["make", "test"]}
    result = ws.run_tests()
    assert not result.ok and ws.last_statuses == {"<command>::make test": "failed"}
    (tmp_path / "Makefile").write_text("test:\n\ttrue\n")
    assert ws.run_tests().passed == 1


def test_a_project_lfs_filter_never_runs_in_a_scratch_workspace(tmp_path, monkeypatch):
    from cleansweep.sandbox.local import open_local

    # as on a machine where git-lfs is configured globally but not installed
    config = tmp_path / "gitconfig"
    config.write_text(
        '[filter "lfs"]\n\tprocess = no-such-git-lfs filter-process\n\trequired = true\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    (project / "data.bin").write_text("version https://git-lfs.github.com/spec/v1\n")
    (project / "mod.py").write_text("A = 1\n")
    ws = open_local(str(project), {"work_dir": str(tmp_path / "ws")})
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ws.path, capture_output=True, text=True, check=True
        ).stdout.split()
        assert {"data.bin", "mod.py"} <= set(tracked)
    finally:
        ws.close()
