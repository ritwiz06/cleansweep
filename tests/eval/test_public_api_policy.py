import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("policy", SCRIPTS / "exp_public_api_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = (
    "def helper():\n    return 2\n\n\n"
    "def keep():\n    a = 1\n    b = 2\n    return a + b\n\n\n"
    "def _hidden():\n    return 3\n"
)


def _diff(tmp_path, before: str, after: str) -> str:
    """A git diff of pkg/mod.py from `before` to `after`."""
    repo = tmp_path / "diffrepo"
    (repo / "pkg").mkdir(parents=True, exist_ok=True)
    (repo / "pkg" / "mod.py").write_text(before)
    run = ["git", "-c", "user.name=x", "-c", "user.email=x@x"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run([*run, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*run, "commit", "-qm", "b"], cwd=repo, check=True)
    (repo / "pkg" / "mod.py").write_text(after)
    out = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, check=True)
    subprocess.run(["rm", "-rf", str(repo)], check=True)
    return out.stdout


def _tree(tmp_path, packaged=True):
    tree = tmp_path / "tree"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "__init__.py").write_text("")
    (tree / "pkg" / "mod.py").write_text(BASE)
    if packaged:
        (tree / "pyproject.toml").write_text('[project]\nname = "pkg"\n')
    return tree


def test_policy_drops_public_dead_code_from_the_final_diff(tmp_path):
    policy = load()
    tree = _tree(tmp_path)
    no_helper = BASE.replace("def helper():\n    return 2\n\n\n", "")
    final = no_helper.replace("\n\n\ndef _hidden():\n    return 3\n", "\n")
    edits = [_diff(tmp_path, BASE, no_helper), _diff(tmp_path, no_helper, final)]
    rep = {
        "plan": {
            "items": [
                {"item_id": "a", "category": "dead_code", "unit": _unit("helper")},
                {"item_id": "b", "category": "dead_code", "unit": _unit("_hidden")},
            ]
        },
        "results": [
            {"item_id": "a", "status": "kept", "diff": edits[0]},
            {"item_id": "b", "status": "kept", "diff": edits[1]},
        ],
    }
    meta, dead, moved = policy.policy_edits(rep, tree)
    assert (meta, dead, [r["item_id"] for r in moved]) == (True, 2, ["a"])
    diff = policy.filtered_diff(tree, _diff(tmp_path, BASE, final), moved)
    assert "-def _hidden" in diff and "def helper" not in diff
    # without packaging metadata the policy (auto) leaves the run alone
    assert policy.policy_edits(rep, _tree(tmp_path / "plain", packaged=False))[2] == []


def _unit(name):
    return {"path": "pkg/mod.py", "kind": "function", "name": name, "start_line": 1}
