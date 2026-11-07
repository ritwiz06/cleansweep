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


def test_a_fresh_injection_has_only_valid_plants(tmp_path):
    inject = load()
    tree = _fresh(tmp_path, "toy")
    key = inject.inject(tree, seed=2)
    assert inject.check_plants(tree, key) == [""] * len(key["plants"])


def test_check_plants_names_each_wrong_answer(tmp_path):
    inject = load()
    tree = _fresh(tmp_path, "toy")
    key = inject.inject(tree, seed=1)
    tag = key["tag"]
    plant = {(p["category"], p["kind"]): p for p in key["plants"]}
    (tree / "use_them.py").write_text(f"import tabulate\nfrom x import _unused_{tag}\n")
    dup = tree / plant["duplicate", "slop"]["paths"][1]
    dup.write_text(dup.read_text().replace('return "-".join(words)', 'return "_".join(words)'))
    near = tree / plant["duplicate", "trap"]["path"]
    near.write_text(near.read_text().replace("int(value * factor + 0.5)", "round(value * factor)"))
    module = plant["unused_import", "slop"]["marker"].split()[1]
    near.write_text(near.read_text() + f"\nUSED = {module}\n")
    reasons = dict(zip(plant, inject.check_plants(tree, key), strict=True))
    assert reasons["unused_dependency", "slop"] == "tabulate is imported by use_them.py"
    assert reasons["dead_code", "slop"] == f"_unused_{tag} has a caller"
    assert reasons["duplicate", "slop"] == "the two copies differ"
    assert reasons["duplicate", "trap"] == "the near-duplicates give the same result"
    assert reasons["unused_import", "slop"] == f"{module} is used"
    assert reasons["dead_code", "trap"] == reasons["leftover_file", "slop"] == ""


def test_the_dependency_plant_skips_a_name_the_project_imports(tmp_path):
    inject = load()
    (tmp_path / "requirements.txt").write_text("requests\n")
    (tmp_path / "make_table.py").write_text("import os, tabulate\n")
    assert inject._plant_dependency(tmp_path, None) == ("requirements.txt", "toolz>=0.1")


def test_the_one_shot_scope_is_what_the_plants_commit_changed(tmp_path):
    inject = load()
    tree = tmp_path / "toy"
    base = inject._git_tree(ROOT / "tests" / "fixtures" / "toy_repo", tree)
    key = inject.inject(tree, seed=1)
    sha = inject._commit(tree, "plants")
    files = inject.planted_files(tree, sha)
    assert {p["path"] for p in key["plants"]} <= set(files)
    copy, applied = inject.final_tree(tree, "", base)
    assert applied and not (copy / key["plants"][0]["path"]).exists()  # the leftover file
    shutil.rmtree(copy.parent)


def test_py_texts_never_walks_git(tmp_path, monkeypatch):
    import os

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    (tmp_path / ".git" / "objects" / "89").mkdir(parents=True)
    (tmp_path / ".git" / "hook.py").write_text("")
    real = os.scandir

    def scandir(path="."):
        if ".git" in Path(path).parts:  # as if a background gc removed it mid-walk
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    assert load()._py_texts(tmp_path) == {"pkg/a.py": "x = 1\n"}
