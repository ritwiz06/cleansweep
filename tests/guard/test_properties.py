"""Property tests on generated inputs (seeded): line-level edits keep a module parseable, and a
rollback restores the tree exactly."""

import ast
import hashlib
import random
import shutil
from pathlib import Path
from types import SimpleNamespace

from cleansweep.guard import apply_edit
from cleansweep.reviewer.lines import run_line_detectors

BLOCKS = [
    "def unused_{n}(x):\n    extra = x * 2\n    return x\n",
    "def multi_{n}(x):\n    tmp = helper(\n        x,\n        1,\n    )\n    return x\n",
    'def shown_{n}(x):\n    print(f"{{x=}}")\n    return x + 1\n',
    "def only_print_{n}(x):\n    print('debug', x)\n",
    "def branch_{n}(x):\n    if x:\n        return 1\n    else:\n        print(x)\n",
    "def check_{n}(x):\n    if x > 0:\n        return True\n    else:\n        return False\n",
    "def notes_{n}(x):\n    # TODO: remove this later\n    return x\n",
    "# old_{n} = helper(1, 2)\n# print(old_{n})\n",
    "# This explains what the next function does.\n",
    'def documented_{n}(x):\n    """Return x."""\n    value = x\n    return x\n',
]


def module(rng: random.Random) -> str:
    """A module of random blocks; some are methods of a class."""
    parts = ["def helper(a, b):\n    return a + b\n"]
    for n in range(rng.randint(2, 7)):
        block = rng.choice(BLOCKS).format(n=n)
        if rng.random() < 0.3 and block.startswith("def "):
            block = f"class Box{n}:\n" + "".join(
                "    " + line if line.strip() else line for line in block.splitlines(True)
            )
            block = block.replace("(x):", "(self, x):", 1)
        parts.append(block)
    return "\n\n".join(parts)


def test_line_edits_keep_every_generated_module_parseable(tmp_path):
    rng = random.Random(572)
    checked = 0
    for case in range(60):
        root = tmp_path / f"case{case}"
        root.mkdir()
        text = module(rng)
        (root / "mod.py").write_text(text)
        items = run_line_detectors(str(root), ["mod.py"])
        for item in items:  # one edit at a time
            one = tmp_path / f"one{case}"
            shutil.copytree(root, one)
            if apply_edit(SimpleNamespace(path=str(one)), item):
                ast.parse((one / "mod.py").read_text())
                checked += 1
            shutil.rmtree(one)
        for item in items:  # all of them in turn, as one package applies them
            apply_edit(SimpleNamespace(path=str(root)), item)
        ast.parse((root / "mod.py").read_text())
    assert checked > 100


def test_a_rollback_restores_the_tree_after_random_edits(toy_ws):
    rng = random.Random(572)
    root = Path(toy_ws.path)
    base, before = toy_ws.checkpoint("base"), tree_hash_without_git(root)
    files = sorted(p for p in root.rglob("*.py") if ".git" not in p.parts)
    for _ in range(5):
        for path in rng.sample(files, 3):
            change = rng.choice(["append", "delete", "new"])
            if change == "append":
                path.write_text(path.read_text() + "\nx = 1\n")
            elif change == "delete":
                path.unlink(missing_ok=True)
            else:
                (path.parent / f"new_{rng.randint(0, 999)}.py").write_text("y = 2\n")
        toy_ws.rollback(base)
        assert tree_hash_without_git(root) == before


def tree_hash_without_git(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(root).parts:
            h.update(str(path.relative_to(root)).encode() + path.read_bytes())
    return h.hexdigest()
