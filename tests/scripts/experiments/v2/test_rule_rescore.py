import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts" / "experiments" / "v2"


def load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "exp_rule_rescore", SCRIPTS / "exp_rule_rescore.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rule_moves_kept_dead_code_and_duplicates_on_framework_methods():
    rescore = load()
    units = [
        ("1", "dead_code", "H.do_GET"),
        ("2", "dead_code", "helper"),
        ("3", "unused_import", "H.do_POST"),
        ("4", "duplicate", "H.do_PUT"),
        ("5", "dead_code", "H.do_HEAD"),
    ]
    report = {
        "plan": {
            "items": [
                {"item_id": i, "category": c, "unit": {"path": "a.py", "name": n}}
                for i, c, n in units
            ]
        },
        "results": [
            {"item_id": i, "status": "rolled_back" if i == "5" else "kept", "diff": "d"}
            for i, _, _ in units
        ],
    }
    graph = SimpleNamespace(framework_callback=lambda key: "http.server" if ".do_" in key else None)
    moved = rescore.moved(report, graph)
    assert [(m["item_id"], m["framework"]) for m in moved] == [
        ("1", "http.server"),
        ("4", "http.server"),
    ]


def test_the_numbers_as_run_come_from_the_report():
    rescore = load()
    plants = [
        {"kind": "slop", "removed": True},
        {"kind": "slop", "removed": False},
        {"kind": "trap", "removed": True},
    ]
    report = {"stats": {"inject": {"plants": plants}, "hidden": {"behavior_changed": True}}}
    assert rescore.as_run(report) == {"slop_removed": 1, "traps_removed": 1, "hidden_changed": True}
