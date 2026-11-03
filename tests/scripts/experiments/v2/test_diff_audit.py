import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_diff_audit.py"

DIFF = """diff --git a/pkg/util.py b/pkg/util.py
--- a/pkg/util.py
+++ b/pkg/util.py
@@ -1,6 +1,2 @@
-import textwrap
 import os
-
-def shorten(text):
-    return textwrap.shorten(text, 10)
"""


def load():
    spec = importlib.util.spec_from_file_location("exp_diff_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_removed_names_come_from_the_minus_lines():
    audit = load()
    assert audit.removed_names(DIFF, "pkg/util.py") == ["textwrap", "shorten"]
    deleted = "deleted file mode 100644\n--- a/scratch.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
    assert audit.removed_names(deleted, "tools/scratch.py") == ["scratch"]


def test_the_auditor_sees_code_diff_and_references_but_no_method(tmp_path):
    audit = load()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text(
        "import textwrap\nimport os\n\ndef shorten(text):\n    return textwrap.shorten(text, 10)\n"
    )
    (tmp_path / "cli.py").write_text("from pkg.util import shorten\nprint(shorten('a b c'))\n")
    edit = {
        "project": "aidev:o/p@abc",
        "path": "pkg/util.py",
        "diff": DIFF,
        "category": "dead_code",
    }
    text = audit.view(edit, audit.Tree(tmp_path))
    assert "Project: aidev:o/p" in text and "@abc" not in text
    assert "    1 import textwrap" in text and "```diff" in text
    assert "`shorten`: 2 line(s) in this file; elsewhere: cli.py:1:" in text
    assert "dead" not in text.lower() and "agentic" not in text
    assert "not searched" in audit.view(edit, audit.Tree(None))


def test_the_injection_rule_settles_only_planted_lines():
    audit = load()
    key = {"tag": "amber1", "plants": [{"category": "unused_import", "marker": "import zlib\n"}]}
    slop, traps = audit.plant_lines(key)
    dead = "@@ -9,5 +9,0 @@\n-def _unused_amber1(items):\n-    total = 0\n-    for item in items:\n"
    dead += "-        total += len(str(item))\n-    return total\n"
    assert audit.plant_rule(dead, slop, traps) == "fine"
    assert audit.plant_rule("@@ -1 +1 @@\n-import zlib\n", slop, traps) == "fine"
    debug = '@@ -3 +3 @@\n-        print(f"{value=}")\n+        pass\n'
    assert audit.plant_rule(debug, slop, traps) == "fine"
    trap = "@@ -20,3 +20,0 @@\n-    def visit_Name(self, node):\n-        self.names += 1\n"
    assert audit.plant_rule(trap, slop, traps) == "wrong"
    support = '@@ -1,2 +1,0 @@\n-def describe_amber1(value, verbose=False):\n-    return "x"\n'
    assert audit.plant_rule(support, slop, traps) == ""  # needs reading
    key["plants"].append({"category": "unused_dependency", "marker": '"toolz>=0.1"'})
    slop, traps = audit.plant_lines(key)
    inline = '@@ -5 +5 @@\n-deps = ["numpy", "toolz>=0.1"]\n+deps = ["numpy"]\n'
    assert audit.plant_rule(inline, slop, traps) == "fine"
    other = '@@ -5 +5 @@\n-deps = ["numpy", "toolz>=0.1"]\n+deps = []\n'
    assert audit.plant_rule(other, slop, traps) == ""


def test_a_removed_dependency_is_named_as_code_imports_it():
    audit = load()
    req = "--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1,2 +1 @@\n"
    req += "-Python-Dateutil>=2.8\n requests\n"
    assert audit.removed_names(req, "requirements.txt") == ["python_dateutil"]
    toml = "--- a/pyproject.toml\n+++ b/pyproject.toml\n@@ -3,2 +3 @@\n"
    toml += '-    "tabulate>=0.9",\n-name = "x"\n'
    assert audit.removed_names(toml, "pyproject.toml") == ["tabulate"]


def test_grep_keeps_a_line_with_a_form_feed(tmp_path):
    audit = load()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x = shorten  # \f page\nprint(shorten)\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=a",
            "-c",
            "user.email=a@b",
            "commit",
            "-qm",
            "a",
        ],
        check=True,
    )
    assert audit.Tree(tmp_path, "HEAD").grep("shorten") == [
        "a.py:1:x = shorten  # \f page",
        "a.py:2:print(shorten)",
    ]
