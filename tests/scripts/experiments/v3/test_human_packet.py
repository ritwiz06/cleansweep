import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_human_packet.py"
REVIEW = (
    "Project: shop-abl-single_agent\nKind: an unused import\nLocation: `pkg/a.py` (`os`)\n\n"
    "Code:\n```\n    1 import os\n```\n\nProposed: Remove the import `os` from `pkg/a.py`.\n\n"
    "Diff:\n```diff\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +0,0 @@\n-import os\n```\n\n"
    "Facts:\n- ruff F401\n- quarantined at /Users/someone/runs/shop-abl-single_agent/q"
)


def load():
    spec = importlib.util.spec_from_file_location("exp_human_packet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def edit(i, method, verdict="", tier="", same=None):
    path = f"pkg/m{i}.py"
    head = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
    diff = f"{head}@@ -20,2 +20,1 @@\n x = 1\n-import json{i}\n"
    code = "\n".join(f"{n:>5} line {n}" for n in range(5, 36))
    view = (
        f"Project: aidev:owner/repo\nFile: `{path}`\n\nCode before the edit:\n```\n{code}\n```\n\n"
        f"Diff:\n```diff\n{diff}\n```\n\nWhere removed names appear (before the edit):\n"
        f"- `json{i}`: 1 line(s) in this file; nowhere else in the project"
    )
    return {
        "edit": f"{i:012x}",
        "same": same or f"change {i}",
        "project": f"aidev:owner/repo@{i}",
        "path": path,
        "diff": diff,
        "view": view,
        "answer": "yes" if verdict else "no",
        "votes": ["yes" if verdict else "no"] * 3,
        "verdict": verdict,
        "checked_by": "reading (LLM-judged)" if verdict else "",
        "tier": tier,
        "methods": {method: 1},
        "runs": [f"injected/{method}/repo-s{i}"],
    }


def data():
    edits = [edit(i, "agentic") for i in range(15)]
    edits += [edit(20, "agentic-single_agent", "wrong", "reading")]
    edits += [edit(21, "cleansweep", "wrong", "reading", same="change 20")]
    edits += [edit(30, "agentic-no_research", "debatable", "reading")]
    rows = [
        {
            "sheet": "shop-abl-single_agent",
            "row": 1,
            "run": "shop-abl-single_agent",
            "project": "aidev:owner/shop@abc",
            "item_id": "x1",
            "kind": "applied",
            "category": "unused_import",
            "decision": "reject",
            "votes": ["reject"] * 3,
            "view": REVIEW,
        },
    ]
    return edits, rows, [f"{30:012x}"], [("shop-abl-single_agent", 1)]


def test_the_draw_is_fixed_by_the_seed_and_keeps_the_calibration_items():
    packet = load()
    items, key = packet.build(*data())
    again, key_again = packet.build(*data())
    assert items == again and key == key_again
    calibration = {v["calibration"] for v in key["items"].values()}
    assert {"audit sheet 1", "C1"} <= calibration
    assert next(iter(key)) == "WARNING"


def test_the_same_change_in_another_run_is_one_item_with_both_methods():
    packet = load()
    _, key = packet.build(*data())
    wrong = [v for v in key["items"].values() if v["llm_label"] == "wrong" and "edits" in v]
    assert len(wrong) == 1
    assert wrong[0]["methods"] == {"agentic-single_agent": 1, "cleansweep": 1}
    assert wrong[0]["group"] == "single agent"


def test_weights_are_changes_per_item_in_the_stratum():
    packet = load()
    _, key = packet.build(*data())
    team_no = next(s for s in key["strata"] if s["label"] == "auditor no")
    assert (team_no["changes"], team_no["items"]) == (15, 12)
    assert team_no["weight"] == 1.25


def test_items_show_no_method_run_path_or_label(tmp_path):
    packet = load()
    items, key = packet.build(*data())
    packet.write_packet(tmp_path, items, key)
    text = (tmp_path / "items.md").read_text() + (tmp_path / "items.html").read_text()
    assert packet.leaks(items) == []
    for word in ("single_agent", "repo-s", "reading", "LLM", "diff --git", "@1"):
        assert word not in text
    assert "Project:** owner/shop" in text and "import json20" in text
    with (tmp_path / "rater_A.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(items) and not any(r["label"] for r in rows)
    assert json.loads((tmp_path / "key.json").read_text())["items"]["1"]["weight"]


def test_a_filled_sheet_is_never_overwritten(tmp_path):
    packet = load()
    (tmp_path / "rater_B.csv").write_text("item,label,confidence,minutes,note\n1,fine,3,,\n")
    with pytest.raises(SystemExit):
        packet.write_packet(tmp_path, *packet.build(*data()))


def test_projects_show_without_commit_dataset_agent_or_run_folder():
    packet = load()
    assert packet.project_name("aidev:owner/repo@abc123") == "owner/repo"
    assert packet.project_name("swebench:pkg__pkg-1:agent_a") == "pkg__pkg-1"
    assert packet.project_name("local:toy_repo") == "toy_repo"
    assert packet.project_name("local:cleansweep-runs-v2b") == "cleansweep"
    assert packet.project_name("local:self_v2c") == "cleansweep"
