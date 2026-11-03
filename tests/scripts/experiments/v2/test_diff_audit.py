import importlib.util
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
