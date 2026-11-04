import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts" / "experiments" / "v2"
STUB = "".join(f"-line {i}\n" for i in range(9)) + "-        raise NotImplementedError\n"


def load():
    sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / "exp_audit_rubric.py"
    spec = importlib.util.spec_from_file_location("exp_audit_rubric", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(edit, verdict, evidence, checked_by="reading (LLM-judged)"):
    return {"edit": edit, "verdict": verdict, "evidence": evidence, "checked_by": checked_by}


def test_a_placeholder_stub_and_its_copies_become_debatable():
    rubric = load()
    a, b, c = "a" * 12, "b" * 12, "c" * 12
    rows = {
        a: row(a, "wrong", "deletes the seed Solution stub"),
        b: row(b, "wrong", f"the same change as {a} (same file): deletes the seed Solution stub"),
        c: row(c, "wrong", "removes jinja2; app.py imports it"),
    }
    audit = {
        a: {"path": "tasks/x/seed/solution.py", "diff": STUB},
        c: {"path": "requirements.txt", "diff": "-jinja2\n"},
    }
    checks, changes = rubric.apply(rows, audit)
    assert [(r["edit"], r["verdict"], r["kind"]) for r in checks] == [
        (a, "debatable", "dynamic handler or stub"),
        (b, "debatable", "dynamic handler or stub"),
        (c, "wrong", "dependency"),
    ]
    assert [x["edit"] for x in changes] == [a, b]
    assert changes[1]["reason"].startswith(f"the same change as {a}: a placeholder Solution")
