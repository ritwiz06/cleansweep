import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_audit_confirm_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_audit_confirm_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_confirm_runner_uses_the_v3_audit_files_and_clones(tmp_path):
    v3 = load()
    confirm = v3.load([tmp_path])
    assert confirm.TESTS == ROOT / "results" / "raw" / "diff_audit_v3" / "tests"
    report = tmp_path / "real_v3" / "o__b" / "agentic-r1" / "report.json"
    target, sandbox = confirm.opened("aidev:o/b@v1", report)
    assert target == "aidev:o/b@v1" and sandbox["aidev_clones"] == "data/raw/aidev/heldout"
    report = tmp_path / "inject_v3" / "o__a-s4" / "agentic.json"
    assert confirm.opened("aidev:o/a@p1", report)[1]["aidev_clones"] == "data/raw/aidev/injected"
