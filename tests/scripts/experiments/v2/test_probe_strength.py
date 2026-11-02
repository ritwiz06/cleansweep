import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_probe_strength.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_probe_strength", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(folder: Path, target_set: str, caught: list[bool]) -> None:
    folder.mkdir()
    mutant = {"experiment": "mutation", "unit": "m.py::f", "operator": "swap_add", "line": 3}
    records = [{**mutant, "caught": c} for c in caught]
    data = {"target_set": target_set, "target": "t", "probe_mode": "runner", "records": records}
    (folder / "t.json").write_text(json.dumps(data))


def test_the_same_mutants_are_compared_in_order(tmp_path):
    probe = load()
    write(tmp_path / "v1", "swebench_t2", [True, False, True])
    write(tmp_path / "v2", "swebench_t2_v2subset", [True, True, False, False])
    (row,) = probe.compare(tmp_path / "v1", tmp_path / "v2")
    assert row["target_set"] == "swebench_t2" and row["matched"] == 3
    assert (row["both"], row["only_v1"], row["only_v2"], row["neither"]) == (1, 1, 1, 0)
    assert row["v2_only_run"] == 1
