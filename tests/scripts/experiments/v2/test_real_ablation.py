import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_real_ablation.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_real_ablation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(project, method, verdict, **numbers):
    out = {f: "0" for f in load().FIELDS}
    out |= {"project": project, "method": method, "verdict": verdict, "ui_check": ""}
    return out | {k: str(v) for k, v in numbers.items()}


def test_the_method_table_sums_runs_and_labels_llm_judged_columns():
    ablation = load()
    rows = [
        row("slop-guard", "team", "nothing applied", llm_requests=61, minutes=1.9),
        row(
            "telegram",
            "team",
            "everything runs",
            packages_kept=1,
            reviewer_accept=1,
            code_edits=1,
            llm_requests=54,
            minutes=3.7,
        ),
        row(
            "telegram",
            "single_agent",
            "everything runs",
            packages_kept=7,
            reviewer_accept=4,
            reviewer_reject=2,
            reviewer_unsure=1,
            code_edits=7,
            wrong=2,
            wrong_confirmed=1,
            debatable=1,
            llm_requests=61,
            minutes=2.8,
        ),
    ]
    team, single = ablation.method_table(rows)
    assert team["verdicts"] == "everything runs 1; nothing applied 1"
    assert team["LLM requests (mean)"] == 57.5 and team["projects"] == 2
    assert single["LLM reviewer accepts kept changes (LLM-judged)"] == "4/6 (1 unsure)"
    assert single["wrong of kept code edits (confirmed by a test, check or rule)"] == "2 of 7 (1)"
    assert single["debatable (LLM-judged reading)"] == 1


def test_reviewer_counts_only_the_kept_changes(tmp_path):
    ablation = load()
    rows = [
        {"n": 1, "kind": "applied"},
        {"n": 2, "kind": "suggestion"},
        {"n": 3, "kind": "applied"},
    ]
    (tmp_path / "review_rows.json").write_text(json.dumps({"rows": rows}))
    reviews = {
        "1": {"decision": "accept"},
        "2": {"decision": "reject"},
        "3": {"decision": "unsure"},
    }
    (tmp_path / "llm_review.json").write_text(json.dumps({"reviews": reviews}))
    assert ablation._reviewer(tmp_path) == {
        "reviewed": 2,
        "reviewer_accept": 1,
        "reviewer_reject": 0,
        "reviewer_unsure": 1,
    }


def test_ui_text_names_what_changed(tmp_path):
    ablation = load()
    result = {
        "ok": False,
        "classes": 44,
        "changed": ["a.B"],
        "lost": [],
        "removed": [],
        "broken": [],
    }
    (tmp_path / "ui_check.json").write_text(json.dumps(result))
    assert ablation._ui_text(tmp_path) == "changed 1"
    result = {
        "ok": True,
        "classes": 44,
        "changed": [],
        "lost": [],
        "removed": ["a.C"],
        "broken": [],
    }
    (tmp_path / "ui_check.json").write_text(json.dumps(result))
    assert ablation._ui_text(tmp_path) == "ok (44 classes, 1 removed by the cleanup)"


def test_diff_counts_net_lines_and_deleted_files():
    diff = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,2 @@\n-a\n-b\n+c\n"
        "diff --git a/y.py b/y.py\ndeleted file mode 100644\n--- a/y.py\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-z\n"
    )
    assert load().diff_counts({"final_diff": diff}) == {"lines_removed": 2, "files_removed": 1}
