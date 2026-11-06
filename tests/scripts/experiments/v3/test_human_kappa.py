import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_human_kappa.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_human_kappa", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet(folder, a, b, llm):
    items = {
        str(n): {"source": "diff audit", "tier": "reading", "llm_label": label}
        for n, label in enumerate(llm, 1)
    }
    (folder / "key.json").write_text(json.dumps({"WARNING": "not for raters", "items": items}))
    for name, labels in (("rater_A.csv", a), ("rater_B.csv", b)):
        lines = ["item,label,confidence,minutes,note"]
        lines += [f"{n},{label},2,," for n, label in enumerate(labels, 1)]
        (folder / name).write_text("\n".join(lines) + "\n")


def rows(path):
    with path.open() as f:
        return {(r["comparison"], r["subset"], r["scale"]): r for r in csv.DictReader(f)}


def test_kappa_between_the_raters_and_against_the_recorded_label(tmp_path):
    kappa = load()
    a = ["wrong", "wrong", "fine", "fine"]
    b = ["wrong", "fine", "fine", "fine"]
    packet(tmp_path, a, b, ["wrong", "debatable", "fine", "fine"])
    out = tmp_path / "human_kappa.csv"
    kappa.main([str(tmp_path), "--out", str(out)])
    found = rows(out)
    # p_o = 3/4, p_e = 1/2 * 1/4 + 1/2 * 3/4 = 1/2: kappa = 0.5
    both = found[("rater_A vs rater_B", "all", "3 labels")]
    assert (both["n"], both["agreement"], both["kappa"]) == ("4", "0.75", "0.5")
    assert float(both["ci_low"]) <= 0.5 <= float(both["ci_high"])
    assert (
        found[("rater_B vs LLM", "diff audit (LLM-judged)", "wrong vs not wrong")]["kappa"] == "1.0"
    )
    assert both["status"] == "human-validated"
    assert ("rater_A vs rater_B", "review sheet", "3 labels") not in found


def test_an_empty_sheet_gives_not_human_validated(tmp_path):
    kappa = load()
    packet(tmp_path, ["fine", "wrong"], ["", ""], ["fine", "wrong"])
    out = tmp_path / "human_kappa.csv"
    kappa.main([str(tmp_path), "--out", str(out)])
    with out.open() as f:
        found = list(csv.DictReader(f))
    assert len(found) == 1
    assert found[0]["status"] == "not human-validated: rater_B.csv missing or blank"
    assert found[0]["kappa"] == ""
