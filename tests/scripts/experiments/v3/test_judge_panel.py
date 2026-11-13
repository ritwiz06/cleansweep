import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_judge_panel.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_judge_panel", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLLM:
    def __init__(self, answers):
        self.answers = answers

    def chat_json(self, messages, temperature, seed):
        label = self.answers[messages[1]["content"]][seed]
        if label == "broken":
            raise ValueError("no json")
        return {"label": label, "reason": "because"}


def packet(folder, tiers):
    text = ["# Rating items", ""]
    items = {}
    for n, (tier, label) in enumerate(tiers, 1):
        text += [f"## Item {n}", "", f"edit {n}", ""]
        items[str(n)] = {"source": "diff audit", "tier": tier, "llm_label": label, "edit": f"e{n}"}
    (folder / "items.md").write_text("\n".join(text))
    (folder / "rubric.md").write_text("# Rubric\n")
    (folder / "key.json").write_text(json.dumps({"items": items}))


def test_items_are_split_by_their_headings(tmp_path):
    panel = load()
    packet(tmp_path, [("reading", "fine"), ("confirmed", "wrong")])
    assert panel.read_items(tmp_path / "items.md") == {"1": "edit 1", "2": "edit 2"}


def test_a_judge_without_a_majority_says_debatable():
    panel = load()
    assert panel.majority(["wrong", "wrong", "fine"]) == "wrong"
    assert panel.majority(["wrong", "fine", "debatable"]) == "debatable"
    assert panel.majority(["none", "none", "fine"]) == "debatable"


def test_wilson_interval():
    panel = load()
    low, high = panel.wilson(9, 10)
    assert (low, high) == (0.596, 0.982)


def test_run_and_table(tmp_path, monkeypatch):
    panel = load()
    packet(tmp_path, [("confirmed", "wrong"), ("confirmed", "fine"), ("reading", "wrong")])
    monkeypatch.setattr(panel, "VOTES", tmp_path / "out" / "judge_panel_votes.csv")
    monkeypatch.setattr(panel, "RAW", tmp_path / "raw")
    answers = {
        "a": {"edit 1": ["wrong"] * 3, "edit 2": ["fine"] * 3, "edit 3": ["fine"] * 3},
        "b": {"edit 1": ["wrong"] * 3, "edit 2": ["wrong"] * 3, "edit 3": ["fine"] * 3},
        "c": {"edit 1": ["broken", "wrong", "wrong"], "edit 2": ["fine"] * 3,
              "edit 3": ["wrong", "fine", "debatable"]},
    }
    votes = panel.run(tmp_path, judges=("a", "b", "c"), make_client=lambda j: FakeLLM(answers[j]))
    with votes.open() as f:
        assert len(list(csv.DictReader(f))) == 27
    out, md = panel.table(votes)
    with out.open() as f:
        rows = {(r["measure"], r["who"], r["subset"], r["scale"]): r for r in csv.DictReader(f)}
    scale = "wrong vs not wrong"
    accuracy = rows[("accuracy", "b", "confirmed verdicts", scale)]
    assert (accuracy["n"], accuracy["value"]) == ("2", "0.5")
    assert rows[("specificity", "panel", "confirmed verdicts", scale)]["value"] == "1.0"
    assert rows[("unusable votes", "c", "all", "3 labels")]["value"] == "1"
    assert rows[("no majority of 3 votes", "c", "all", "3 labels")]["value"] == "1"
    # item 3: a fine, b fine, c debatable -> the panel says fine, overturning the recorded wrong
    reading = rows[("agrees with the reading", "panel", "diff audit (reading tier)", "3 labels")]
    assert (reading["n"], reading["value"]) == ("1", "0")
    assert "| 3 | e3 | wrong | fine | fine | fine | debatable |" in md.read_text()
