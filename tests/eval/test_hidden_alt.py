from pathlib import Path

from cleansweep.eval.hidden import (
    HIDDEN_DIR,
    run_alt_hidden,
    without_install_files,
    write_alt_tests,
)
from cleansweep.llm import FakeLLM
from cleansweep.sandbox import open_workspace
from cleansweep.sandbox.workspace import Workspace
from cleansweep.workflow import run_sweep

SRC = Path(__file__).resolve().parents[2] / "src" / "cleansweep"
UTILS_TESTS = """```python
from shopcart.utils import round_price, slugify


def test_slugify():
    assert slugify("Hello  World") == "hello-world"


def test_round_price():
    assert round_price(None) == 0.0
```"""


def alt_cfg(cfg, tmp_path):
    return {**cfg, "exp": {**cfg["exp"], "hidden_alt_cache": str(tmp_path / "alt")}}


def slugify_diff(toy_repo, sandbox_cfg) -> str:
    ws = open_workspace(toy_repo, sandbox_cfg)
    try:
        path = Path(ws.path) / "shopcart" / "utils.py"
        path.write_text(path.read_text().replace('"-".join', '"_".join'))
        return ws.diff(ws.base)
    finally:
        ws.close()


def test_alt_tests_are_cached_and_ignored_by_git(toy_repo, cfg, tmp_path):
    cfg = alt_cfg(cfg, tmp_path)
    llm = FakeLLM({"shopcart.utils": UTILS_TESTS})
    ws = open_workspace(toy_repo, cfg["core"]["sandbox"])
    try:
        files = write_alt_tests(ws, toy_repo, cfg, llm)
        assert files and all(f.startswith(f"{HIDDEN_DIR}/test_cs_alt_") for f in files)
        assert any("slugify" in (Path(ws.path) / f).read_text() for f in files)
        assert ws.diff(ws.base) == ""  # git ignores them, so no cleanup diff can carry them
        calls = len(llm.calls)
        assert write_alt_tests(ws, toy_repo, cfg, llm) == files
        assert len(llm.calls) == calls  # the second time they come from the cache
    finally:
        ws.close()


def test_alt_hidden_checks_see_a_behavior_change(toy_repo, cfg, tmp_path):
    cfg = alt_cfg(cfg, tmp_path)
    llm = FakeLLM({"shopcart.utils": UTILS_TESTS})
    same = run_alt_hidden(toy_repo, "", cfg, llm)
    assert same["available"] and same["behavior_changed"] is False
    assert same["alt_tests"] >= 2 and same["alt_passing"] >= 2
    changed = run_alt_hidden(toy_repo, slugify_diff(toy_repo, cfg["core"]["sandbox"]), cfg, llm)
    assert changed["behavior_changed"] is True
    assert any("test_slugify" in t for t in changed["alt_changed"])


def test_install_files_are_left_out_of_the_diff():
    code = (
        "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +0,0 @@\n-x = 1\n"
    )
    info = (
        "diff --git a/src/UNKNOWN.egg-info/PKG-INFO b/src/UNKNOWN.egg-info/PKG-INFO\n"
        "new file mode 100644\n--- /dev/null\n+++ b/src/UNKNOWN.egg-info/PKG-INFO\n"
        "@@ -0,0 +1 @@\n+Name: UNKNOWN\n"
    )
    assert without_install_files(info + code) == code
    assert without_install_files(code + info) == code
    assert without_install_files("") == ""


def test_install_files_in_the_diff_do_not_stop_the_alt_checks(toy_repo, cfg, tmp_path):
    cfg = alt_cfg(cfg, tmp_path)
    llm = FakeLLM({"shopcart.utils": UTILS_TESTS})
    # a tracked egg-info file the sweep's install rewrote; the fresh workspace's install differs
    info = (
        "diff --git a/src/UNKNOWN.egg-info/PKG-INFO b/src/UNKNOWN.egg-info/PKG-INFO\n"
        "--- a/src/UNKNOWN.egg-info/PKG-INFO\n+++ b/src/UNKNOWN.egg-info/PKG-INFO\n"
        "@@ -1 +1 @@\n-Name: UNKNOWN\n+Name: shopcart\n"
    )
    diff = info + slugify_diff(toy_repo, cfg["core"]["sandbox"])
    result = run_alt_hidden(toy_repo, diff, cfg, llm)
    assert result["applied"] is True and result["behavior_changed"] is True


def test_guard_never_sees_the_alt_tests(toy_repo, cfg, tmp_path, monkeypatch):
    cfg = alt_cfg(cfg, tmp_path)
    ws = open_workspace(toy_repo, cfg["core"]["sandbox"])
    write_alt_tests(ws, toy_repo, cfg, FakeLLM({"shopcart.utils": UTILS_TESTS}))
    ws.close()
    seen = []
    run_tests = Workspace.run_tests

    def spy(self, test_paths=None, timeout=900):
        alt = sorted(p.name for p in Path(self.path).rglob("test_cs_alt_*.py"))
        seen.append((list(test_paths or []), alt))
        return run_tests(self, test_paths, timeout)

    monkeypatch.setattr(Workspace, "run_tests", spy)
    report = run_sweep(toy_repo, cfg, "cleansweep")
    assert seen  # the Guard ran the tests
    for paths, alt in seen:
        assert not alt and not any(HIDDEN_DIR in p for p in paths)
    assert HIDDEN_DIR not in report.stats["final_diff"]


def test_guard_side_code_never_mentions_the_alt_tests():
    for package in ("guard", "sandbox", "workflow", "reviewer", "scheduler", "ranking"):
        for path in (SRC / package).rglob("*.py"):
            text = path.read_text()
            assert "test_cs_alt" not in text and "hidden_alt" not in text, path
