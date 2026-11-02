import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_inject.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_inject", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plants_are_scored_and_the_hidden_test_guards_the_traps(tmp_path):
    inject = load()
    tree = tmp_path / "toy"
    shutil.copytree(ROOT / "tests" / "fixtures" / "toy_repo", tree)
    key = inject.inject(tree, seed=1)
    kinds = sorted((p["category"], p["kind"]) for p in key["plants"])
    assert ("duplicate", "trap") in kinds and ("dead_code", "trap") in kinds
    assert {c for c, k in kinds if k == "slop"} == set(inject.CATEGORIES)
    assert inject.inject(_fresh(tmp_path, "again"), seed=1) == key  # the seed fixes everything
    (tree / "hidden").mkdir()
    (tree / "hidden" / "test_planted.py").write_text(key["hidden_test"])
    run = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "hidden"]
    assert subprocess.run(run, cwd=tree, capture_output=True).returncode == 0
    assert not any(p["removed"] for p in inject.score(tree, key))
    leftover = next(p for p in key["plants"] if p["category"] == "leftover_file")
    (tree / leftover["path"]).unlink()
    trap = next(p for p in key["plants"] if p["category"] == "dead_code" and p["kind"] == "trap")
    path = tree / trap["path"]
    path.write_text(
        path.read_text().replace("def visit_Name(self, node):", "def visit_X(self, node):")
    )
    removed = {(p["category"], p["kind"]) for p in inject.score(tree, key) if p["removed"]}
    assert removed == {("leftover_file", "slop"), ("dead_code", "trap")}
    assert subprocess.run(run, cwd=tree, capture_output=True).returncode != 0  # the trap's behavior


def _fresh(tmp_path, name):
    tree = tmp_path / name
    shutil.copytree(ROOT / "tests" / "fixtures" / "toy_repo", tree)
    return tree
