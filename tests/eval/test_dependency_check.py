import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("dep_check", SCRIPTS / "exp_dependency_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_csv_state_leaves_the_requiring_packages_out():
    module = load()
    assert module.csv_state("required by typer") == "required by another package"
    assert module.csv_state("required by anyio, httpx") == "required by another package"
    assert module.csv_state("hidden") == "hidden"
    assert module.csv_state("not installed") == "not installed"
