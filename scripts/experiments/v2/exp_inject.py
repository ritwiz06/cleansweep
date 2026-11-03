"""Slop-injection benchmark: plant known slop and traps into a project at a fixed seed, run each
method on it, and score what it removed.

    python scripts/experiments/v2/exp_inject.py run [--repos toy owner/name ...] [--seeds 1]
        [--methods agentic cleansweep one_shot_llm agentic-<ablation> ...]
    python scripts/experiments/v2/exp_inject.py table
    python scripts/experiments/v2/exp_inject.py validate [--repos ...] [--seeds 1]

Plants (one each, in three of the project's own package modules chosen by the seed):
- slop the cleanup should remove: a leftover file (scratch_<tag>.py), a dead function, an
  exact duplicate (the same function in two modules, both used), an unused import, a debug
  print (f"{value=}"), a commented-out block, an unused dependency;
- traps it must keep: a near-duplicate (the same function rounding half-even in one module and
  half-up in the other) and a framework callback (an ast.NodeVisitor's visit_Name, which only
  the visitor calls, by name).
A hidden test the methods never see (kept outside the project) checks the planted code's
behavior before and after the method's final diff.

Every plant is checked before a run (check_plants): the leftover file, dead function, unused
import and unused dependency are used nowhere (scripts and tests included), the duplicate's two
copies match, the debug print and commented-out block are there once, and both traps behave
differently from what removing them would give. An invalid plant is dropped and listed in the
key. The hidden test must pass on the injected project before any cleanup; when it does not
(a planted module that cannot be imported), the modules are drawn again, up to ATTEMPTS times.
`validate` runs the plant checks on keys already prepared.

The toy repo is copied as a local project; an AIDev repository becomes an injected clone
(data/raw/aidev/injected/<owner>__<name>: its head plus one commit with the plants) and runs,
like every AIDev target, only inside its container; each seed is one commit on the same base,
tagged s<seed>. Every method sees the whole project, except the one-shot baseline, which is shown
the files the plants commit changed (as it is shown the agent's files on AIDev).
Writes results/raw/inject/<name>-s<seed>/ (the key, the hidden test, one report per method with
its score) and, with `table`, results/summary/v2/injection.csv (per repository, method and
category) and injection_summary.csv (per method and category: recall, precision against the
traps, traps kept, hidden behavior changed).
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from methods_v2 import LABELS, resolve  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import save_json  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402
from cleansweep.workflow import run_sweep  # noqa: E402

RAW = ROOT / "results" / "raw" / "inject"
CLONES = "data/raw/aidev/injected"
SUMMARY = ROOT / "results" / "summary" / "v2"
REPOS = [
    "toy",
    "FangYuan33/easy-code-reader",
    "eric-tramel/slop-guard",
    "Usagi-org/ai-goofish-monitor",
    "thomasjjj/Telegram-Snowball-Sampling",
    "utensils/mcp-nixos",
    "trailofbits/dropkit",
    "curvedinf/wove",
    "Human-Agent-Society/CORAL",
    "marin-community/haliax",
]
# Left out, with the reason (reported beside the results).
EXCLUDED = {
    "wkentaro/imgviz": "replaced by request: its hidden test failed before any cleanup (one "
    "planted module, getting_started.py, is a demo script that runs matplotlib and sample data "
    "on import); its planted dependency was valid (generate_readme.py defines a local function "
    "named tabulate and imports nothing by that name)",
    "Fu-Jie/openwebui-extensions": "its hidden test failed on the injected baseline in all 3 "
    "draws (the plugin modules import open_webui, which the project does not install); "
    "replaced by marin-community/haliax",
    "gotalab/skillport": "fewer than 3 importable modules to plant in",
    "posit-dev/chatlas": "fewer than 3 importable modules to plant in (tried as the tenth project)",
}
METHODS = ["agentic", "cleansweep", "one_shot_llm"]  # the default comparison
ATTEMPTS = 3
WORDS = ["amber", "basil", "cedar", "delta", "ember", "fjord", "garnet", "harbor", "indigo"]
STDLIB = ["textwrap", "fnmatch", "zlib", "sched", "colorsys", "netrc"]
DEPS = ["tabulate", "toolz", "humanize", "termcolor"]
GIT = ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.com"]
GIT += ["-c", "commit.gpgsign=false"]
CATEGORIES = [
    "leftover_file",
    "dead_code",
    "duplicate",
    "unused_import",
    "debug_leftover",
    "commented_code",
    "unused_dependency",
]
SKIP_DIRS = {"tests", "test", "docs", "examples", "benchmark", "benchmarks", "scripts", "build"}


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def pick_modules(root: Path, rng: random.Random, n: int = 3) -> list[Path]:
    """n modules that parse and import by name (not tests or scripts): package modules first,
    then modules in plain folders (namespace packages)."""
    packages, plain = [], []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts[:-1]):
            continue
        if path.name.startswith(("test_", "_")) or path.name in ("conftest.py", "setup.py"):
            continue
        if not all(p.isidentifier() for p in [*rel.parts[:-1], path.stem]):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "__main__" in text or len(text.splitlines()) < 15:
            continue
        try:
            ast.parse(text)
        except SyntaxError:
            continue
        (packages if (path.parent / "__init__.py").exists() else plain).append(path)
    if len(packages) >= n:
        return rng.sample(packages, n)
    if len(packages) + len(plain) < n:
        raise ValueError(f"{root}: fewer than {n} importable modules to plant in")
    return packages + rng.sample(plain, n - len(packages))


def _after_imports(text: str) -> int:
    """The line index after the module's last top-level import (or its docstring)."""
    tree = ast.parse(text)
    end = 0
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            end = node.end_lineno
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and end == 0:
            end = node.end_lineno
        elif end:
            break
    return end


def _append(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(text.rstrip("\n") + "\n\n\n" + block.strip("\n") + "\n", encoding="utf-8")


def inject(root: Path, seed: int, attempt: int = 0) -> dict:
    """Plant the slop and the traps; return the key (what was planted where). A later attempt
    draws other modules for the same seed."""
    rng = random.Random(seed if attempt == 0 else f"{seed}.{attempt}")
    tag = f"{rng.choice(WORDS)}{seed}"
    a, b, c = pick_modules(root, rng)
    names = {p: _module_name(root, p) for p in (a, b, c)}
    plants = []

    def plant(category, kind, path, marker, count=1):
        rel = path.relative_to(root).as_posix()
        plants.append(
            {"category": category, "kind": kind, "path": rel, "marker": marker, "count": count}
        )

    leftover = a.parent / f"scratch_{tag}.py"
    leftover.write_text(
        f'"""Trying out the {tag} totals; not used anywhere."""\n\nvalues = [1, 2, 3]\n'
        "print(sum(values))\n",
        encoding="utf-8",
    )
    plant("leftover_file", "slop", leftover, "file")
    _append(
        a,
        f"def _unused_{tag}(items):\n    total = 0\n    for item in items:\n"
        "        total += len(str(item))\n    return total",
    )
    plant("dead_code", "slop", a, f"def _unused_{tag}(")
    slug = (
        f"def slugify_{tag}(text):\n"
        '    words = "".join(c if c.isalnum() else " " for c in text.lower()).split()\n'
        '    return "-".join(words)\n\n\n'
        f'_SLUG_{tag} = slugify_{tag}("Planted Example")'
    )
    _append(a, slug)
    _append(b, slug)
    plant("duplicate", "slop", a, f"def slugify_{tag}(", count=2)
    plants[-1]["paths"] = [a.relative_to(root).as_posix(), b.relative_to(root).as_posix()]
    loop = "    out = []\n    for value in values:\n"
    _append(
        a,
        f"def scale_{tag}(values, factor=100):\n{loop}"
        "        out.append(round(value * factor) / factor)\n    return out\n\n\n"
        f"_SCALED_{tag} = scale_{tag}([0.125])",
    )
    _append(
        b,
        f"def scale_{tag}_v2(values, factor=100):\n{loop}"
        "        out.append(int(value * factor + 0.5) / factor)\n    return out\n\n\n"
        f"_SCALED_{tag}_V2 = scale_{tag}_v2([0.125])",
    )
    plant("duplicate", "trap", b, "int(value * factor + 0.5) / factor")
    text = b.read_text(encoding="utf-8")
    module = next(m for m in STDLIB if not re.search(rf"\b{m}\b", text))
    lines = text.splitlines(keepends=True)
    at = _after_imports(text)
    lines.insert(at, f"import {module}\n")
    b.write_text("".join(lines), encoding="utf-8")
    plant("unused_import", "slop", b, f"import {module}\n")
    _append(
        c,
        f"def describe_{tag}(value, verbose=False):\n    if verbose:\n"
        '        print(f"{value=}")\n'
        f'    return f"value: {{value}}"\n\n\n_DESCRIBED_{tag} = describe_{tag}(1)\n'
        f"# result = describe_{tag}(2, verbose=True)\n# if result:\n#     print(result)",
    )
    plant("debug_leftover", "slop", c, 'print(f"{value=}")')
    plant("commented_code", "slop", c, f"# result = describe_{tag}(2, verbose=True)")
    _append(
        c,
        f"import ast as _ast_{tag}  # noqa: E402\n\n\n"
        f"class _NameCounter{tag.title()}(_ast_{tag}.NodeVisitor):\n"
        "    def __init__(self):\n        self.names = 0\n\n"
        "    def visit_Name(self, node):\n        self.names += 1\n"
        "        self.generic_visit(node)\n\n\n"
        f"def count_names_{tag}(source):\n    counter = _NameCounter{tag.title()}()\n"
        f"    counter.visit(_ast_{tag}.parse(source))\n    return counter.names\n\n\n"
        f'_NAMES_{tag} = count_names_{tag}("x = y")',
    )
    plant("dead_code", "trap", c, "def visit_Name(self, node):")
    dep = _plant_dependency(root, rng)
    if dep:
        plant("unused_dependency", "slop", root / dep[0], dep[1])
    hidden = (
        "import importlib\n\n\ndef test_planted_behavior():\n"
        f'    a = importlib.import_module("{names[a]}")\n'
        f'    b = importlib.import_module("{names[b]}")\n'
        f'    c = importlib.import_module("{names[c]}")\n'
        f'    assert a._SLUG_{tag} == b._SLUG_{tag} == "planted-example"\n'
        f"    assert a._SCALED_{tag} == [0.12]\n"
        f"    assert b._SCALED_{tag}_V2 == [0.13]\n"
        f'    assert c._DESCRIBED_{tag} == "value: 1"\n'
        f"    assert c._NAMES_{tag} == 2\n"
    )
    return {
        "seed": seed,
        "tag": tag,
        "modules": list(names.values()),
        "plants": plants,
        "hidden_test": hidden,
    }


def _plant_dependency(root: Path, rng: random.Random) -> tuple[str, str] | None:
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    taken = (pyproject.read_text() if pyproject.exists() else "") + (
        requirements.read_text() if requirements.exists() else ""
    )
    used = imported_names(root)
    name = next(d for d in DEPS if d not in taken.lower() and d not in used)
    if pyproject.exists():
        import tomlkit

        doc = tomlkit.parse(pyproject.read_text())
        deps = doc.get("project", {}).get("dependencies")
        if deps is not None:
            deps.append(f"{name}>=0.1")
            pyproject.write_text(tomlkit.dumps(doc))
            return "pyproject.toml", f'"{name}>=0.1"'
    if requirements.exists():
        requirements.write_text(requirements.read_text().rstrip("\n") + f"\n{name}>=0.1\n")
        return "requirements.txt", f"{name}>=0.1"
    return None


def _py_texts(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] != ".git":
            out[rel.as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return out


def imported_names(root: Path) -> dict[str, str]:
    """Top-level module name -> the first file importing it, over every .py file in the tree."""
    out = {}
    for rel, text in _py_texts(root).items():
        names = re.findall(r"^\s*from\s+([A-Za-z_]\w*)", text, re.M)
        for line in re.findall(r"^\s*import\s+([^\n#]+)", text, re.M):
            names += [part.split()[0].split(".")[0] for part in line.split(",") if part.strip()]
        for name in names:
            out.setdefault(name, rel)
    return out


def _node(text: str, name: str) -> ast.AST | None:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.name == name:
            return node
    return None


def _run(text: str, names: list[str], call: str, scope: dict) -> object:
    """Run the named definitions from a module's text on their own, then evaluate call."""
    for name in names:
        exec(ast.get_source_segment(text, _node(text, name)), scope)
    return eval(call, scope)


def check_plants(root: Path, key: dict) -> list[str]:
    """Per plant, in key order: why it would be a wrong answer ("" when it is valid)."""
    texts = _py_texts(root)
    tag = key["tag"]
    reasons = []
    for plant in key["plants"]:
        text = texts.get(plant["path"], "")
        category, kind = plant["category"], plant["kind"]
        reason = ""
        if category == "leftover_file":
            stem = Path(plant["path"]).stem
            users = [r for r, x in texts.items() if stem in x and r != plant["path"]]
            reason = f"{stem} is used in {users[0]}" if users else ""
        elif category == "dead_code" and kind == "slop":
            uses = sum(x.count(f"_unused_{tag}") for x in texts.values())
            reason = f"_unused_{tag} has a caller" if uses != 1 else ""
        elif category == "duplicate" and kind == "slop":
            a, b = (texts.get(p, "") for p in plant["paths"])
            same = [_node(x, f"slugify_{tag}") for x in (a, b)]
            if None in same or ast.dump(same[0]) != ast.dump(same[1]):
                reason = "the two copies differ"
        elif category == "duplicate" and kind == "trap":
            a = next(x for r, x in texts.items() if f"def scale_{tag}(" in x)
            one = _run(a, [f"scale_{tag}"], f"scale_{tag}([0.125])", {})
            two = _run(text, [f"scale_{tag}_v2"], f"scale_{tag}_v2([0.125])", {})
            reason = "the near-duplicates give the same result" if one == two else ""
        elif category == "dead_code" and kind == "trap":
            scope = {f"_ast_{tag}": ast}
            names = [f"_NameCounter{tag.title()}", f"count_names_{tag}"]
            kept = _run(text, names, f'count_names_{tag}("x = y")', scope)
            gone = _run(
                text.replace("def visit_Name(", "def _visit_removed("),
                names,
                f'count_names_{tag}("x = y")',
                scope,
            )
            reason = "removing visit_Name changes nothing" if kept == gone else ""
        elif category == "unused_import":
            module = plant["marker"].split()[1]
            reason = f"{module} is used" if len(re.findall(rf"\b{module}\b", text)) != 1 else ""
        elif category in ("debug_leftover", "commented_code"):
            reason = "" if text.count(plant["marker"]) == 1 else "not planted once"
        elif category == "unused_dependency":
            dep = re.match(r'"?([A-Za-z0-9_.-]+?)[<>=]', plant["marker"]).group(1)
            user = imported_names(root).get(dep.replace("-", "_"))
            reason = f"{dep} is imported by {user}" if user else ""
        reasons.append(reason)
    return reasons


def present(root: Path, plant: dict) -> int:
    """How many copies of a plant are still in a tree."""
    if plant["marker"] == "file":
        return int((root / plant["path"]).exists())
    paths = plant.get("paths") or [plant["path"]]
    count = 0
    for rel in paths:
        path = root / rel
        if path.exists():
            count += path.read_text(encoding="utf-8", errors="replace").count(plant["marker"])
    return count


def score(root: Path, key: dict) -> list[dict]:
    """Per plant: planted copies, copies left, and whether the method removed it."""
    out = []
    for plant in key["plants"]:
        left = present(root, plant)
        removed = left < plant["count"]
        out.append({**plant, "left": left, "removed": removed})
    return out


def _git_tree(src: Path, dest: Path) -> str:
    dest.mkdir(parents=True)
    subprocess.run(["cp", "-R", f"{src}/.", str(dest)], check=True)
    subprocess.run([*GIT, "init", "-q"], cwd=dest, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=dest, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "base"], cwd=dest, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, check=True
    ).stdout.strip()


def prepare(repo: str, seed: int, cfg: dict) -> tuple[str, Path, dict]:
    """(target, the injected tree, its key) for the toy repo or an AIDev repository, with the
    invalid plants dropped and a hidden test that passes before any cleanup."""
    name = "toy" if repo == "toy" else repo.replace("/", "__")
    folder = RAW / f"{name}-s{seed}"
    (folder / "hidden").mkdir(parents=True, exist_ok=True)
    rejected = []
    for attempt in range(ATTEMPTS):
        tree = _toy_tree(folder) if repo == "toy" else _injected_base(repo, name, cfg)
        key = inject(tree, seed, attempt)
        reasons = check_plants(tree, key)
        pairs = list(zip(key["plants"], reasons, strict=True))
        key["dropped"] = [{**p, "reason": r} for p, r in pairs if r]
        key["plants"] = [p for p, r in pairs if not r]
        sha = _commit(tree, "plants")
        target = str(tree) if repo == "toy" else f"aidev:{repo}@{sha}"
        if repo != "toy":
            subprocess.run(["git", "tag", "-f", f"s{seed}", sha], cwd=tree, capture_output=True)
        (folder / "hidden" / "test_planted.py").write_text(key["hidden_test"])
        baseline = hidden_baseline(target, folder / "hidden", cfg)
        if baseline["ok"]:
            key.update(target=target, sha=sha, attempt=attempt, rejected=rejected)
            key["hidden_baseline"] = baseline
            (folder / "key.json").write_text(json.dumps(key, indent=1))
            return target, tree, key
        rejected.append({"attempt": attempt, "modules": key["modules"], **baseline})
    (folder / "rejected.txt").write_text(json.dumps(rejected, indent=1))
    raise ValueError(f"the hidden test fails before any cleanup in {ATTEMPTS} draws")


def _injected_base(repo: str, name: str, cfg: dict) -> Path:
    """The injected clone, checked out clean at its base commit (the repository's head). Earlier
    seeds stay in it as tagged commits."""
    from cleansweep.data import load_repos
    from cleansweep.data.swebench import data_path

    tree = data_path(CLONES) / name
    if not (tree / ".git").exists():
        ref = next(r for r in load_repos() if r.repo_id.removeprefix("aidev:") == repo)
        clone = data_path(cfg["data"]["aidev"]["clones"]) / name
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.Popen(
                ["git", "archive", ref.head_sha], cwd=clone, stdout=subprocess.PIPE
            )
            subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, check=True)
            archive.wait()
            _git_tree(Path(tmp), tree)
        return tree
    _tag_prepared(tree, name)
    base = _git(tree, "rev-list", "--max-parents=0", "HEAD").split()[0]
    _git(tree, "checkout", "-q", "--detach", base)
    _git(tree, "reset", "-q", "--hard")
    _git(tree, "clean", "-qfdx")
    return tree


def _toy_tree(folder: Path) -> Path:
    tree = folder / "repo"
    if tree.exists():
        shutil.rmtree(tree)
    _git_tree(ROOT / "tests" / "fixtures" / "toy_repo", tree)
    return tree


def _tag_prepared(tree: Path, name: str) -> None:
    """Tag the plants commit of every seed already prepared, so it outlives a new checkout."""
    for key_path in RAW.glob(f"{name}-s*/key.json"):
        sha = json.loads(key_path.read_text())["target"].partition("@")[2]
        seed = key_path.parent.name.rsplit("-s", 1)[1]
        subprocess.run(["git", "tag", "-f", f"s{seed}", sha], cwd=tree, capture_output=True)


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=tree, capture_output=True, text=True, check=True
    ).stdout.strip()


def hidden_baseline(target: str, hidden: Path, cfg: dict) -> dict:
    """The hidden test on the injected project before any cleanup, in a fresh workspace."""
    ws = open_workspace(target, cfg["core"].get("sandbox"))
    try:
        shutil.copytree(hidden, Path(ws.path) / "_cs_hidden")
        if hasattr(ws, "sync"):
            ws.sync()
        result = ws.run_tests(["_cs_hidden"])
        return {"ok": result.ok, "passed": result.passed, "failed_ids": result.failed_ids}
    finally:
        ws.close()


def _commit(tree: Path, message: str) -> str:
    subprocess.run([*GIT, "add", "-A"], cwd=tree, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", message], cwd=tree, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True, check=True
    ).stdout.strip()


def hidden_check(target: str, final_diff: str, hidden: Path, cfg: dict) -> dict:
    """The planted behavior test, before and after the final diff, in a fresh workspace."""
    ws = open_workspace(target, cfg["core"].get("sandbox"))
    try:
        dest = Path(ws.path) / "_cs_hidden"
        shutil.copytree(hidden, dest)
        if hasattr(ws, "sync"):
            ws.sync()
        before = ws.run_tests(["_cs_hidden"])
        if final_diff.strip() and not ws.apply_patch(final_diff):
            return {"applied": False, "behavior_changed": None}
        after = ws.run_tests(["_cs_hidden"])
        return {
            "applied": True,
            "before_ok": before.ok,
            "after_ok": after.ok,
            "behavior_changed": before.ok != after.ok or before.failed_ids != after.failed_ids,
        }
    finally:
        ws.close()


def final_tree(tree: Path, final_diff: str, sha: str = "HEAD") -> tuple[Path, bool]:
    """A temporary copy of the injected tree at sha with the final diff applied."""
    tmp = Path(tempfile.mkdtemp(prefix="cs_inject_"))
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(tree), str(tmp / "t")], check=True)
    subprocess.run(["git", "checkout", "-q", sha], cwd=tmp / "t", check=True)
    ok = True
    if final_diff.strip():
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=tmp / "t",
            input=final_diff if final_diff.endswith("\n") else final_diff + "\n",
            text=True,
            capture_output=True,
        )
        ok = proc.returncode == 0
    return tmp / "t", ok


def run_one(repo: str, seed: int, method: str, cfg: dict) -> dict:
    name = "toy" if repo == "toy" else repo.replace("/", "__")
    folder = RAW / f"{name}-s{seed}"
    key = json.loads((folder / "key.json").read_text())
    target = key["target"]
    from cleansweep.data.swebench import data_path

    tree = folder / "repo" if repo == "toy" else data_path(CLONES) / name
    sha = key.get("sha") or (_git(tree, "rev-parse", "HEAD") if repo == "toy" else "")
    sha = sha or target.partition("@")[2]
    label, judge, agents = resolve("cleansweep-gatekeeper" if method == "cleansweep" else method)
    if agents:
        cfg = {**cfg, "core": {**cfg["core"], "agents": {**cfg["core"]["agents"], **agents}}}
    if method == "one_shot_llm":
        cfg = {**cfg, "exp": {**cfg.get("exp", {}), "one_shot_paths": planted_files(tree, sha)}}
    if judge:
        os.environ["CLEANSWEEP_JUDGE_MODE"] = judge
    else:
        os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    t0 = time.time()
    cfg = {**cfg, "agent_out": str(folder / f"{method}_run")}
    report = run_sweep(target, cfg, label)
    minutes = round((time.time() - t0) / 60, 2)
    diff = report.stats.get("final_diff", "")
    after, applied = final_tree(tree, diff, sha)
    try:
        scored = score(after, key)
    finally:
        shutil.rmtree(after.parent, ignore_errors=True)
    hidden = hidden_check(target, diff, folder / "hidden", cfg)
    report.stats.update(
        minutes=minutes, inject={"applied": applied, "plants": scored}, hidden=hidden
    )
    save_json(report, folder / f"{method}.json")
    return {
        "repo": repo,
        "seed": seed,
        "method": method,
        "minutes": minutes,
        "removed": sum(p["removed"] for p in scored if p["kind"] == "slop"),
        "traps_removed": sum(p["removed"] for p in scored if p["kind"] == "trap"),
        "hidden_changed": hidden.get("behavior_changed"),
    }


def planted_files(tree: Path, sha: str) -> list[str]:
    """The files the plants commit added or changed: the one-shot baseline's scope."""
    out = _git(tree, "diff", "--name-only", "--diff-filter=AM", f"{sha}~1", sha)
    return sorted(out.split())


def validate(repos: list[str], seeds: list[int]) -> list[dict]:
    """The plant checks on keys already prepared, with the hidden test's baseline result from
    the reports run on them."""
    from cleansweep.data.swebench import data_path

    out = []
    for repo in repos:
        name = "toy" if repo == "toy" else repo.replace("/", "__")
        for seed in seeds:
            folder = RAW / f"{name}-s{seed}"
            if not (folder / "key.json").exists():
                continue
            key = json.loads((folder / "key.json").read_text())
            tree = folder / "repo" if repo == "toy" else data_path(CLONES) / name
            sha = key.get("sha") or key["target"].partition("@")[2] or "HEAD"
            copy, _ = final_tree(tree, "", sha)
            try:
                reasons = check_plants(copy, key)
            finally:
                shutil.rmtree(copy.parent, ignore_errors=True)
            before = {
                json.loads(r.read_text())["stats"].get("hidden", {}).get("before_ok")
                for r in folder.glob("*.json")
                if r.name != "key.json"
            }
            out.append(
                {
                    "repo": repo,
                    "seed": seed,
                    "invalid": {
                        f"{p['category']}/{p['kind']}": r
                        for p, r in zip(key["plants"], reasons, strict=True)
                        if r
                    },
                    "hidden_before_ok": sorted(before - {None}),
                }
            )
    return out


def table() -> tuple[Path, Path]:
    rows = []
    for path in sorted(RAW.glob("*-s*/*.json")):
        if path.name == "key.json":
            continue
        data = json.loads(path.read_text())
        inj = data["stats"].get("inject")
        if not inj:
            continue
        repo = path.parent.name.rsplit("-s", 1)[0]
        for plant in inj["plants"]:
            rows.append(
                {
                    "repo": repo,
                    "seed": path.parent.name.rsplit("-s", 1)[1],
                    "method": path.stem,
                    "category": plant["category"],
                    "kind": plant["kind"],
                    "removed": int(plant["removed"]),
                    "hidden_changed": data["stats"].get("hidden", {}).get("behavior_changed"),
                    "llm_calls": data["stats"].get("llm_calls"),
                    "test_runs": data["stats"].get("test_runs"),
                    "minutes": data["stats"].get("minutes"),
                }
            )
    SUMMARY.mkdir(parents=True, exist_ok=True)
    detail = SUMMARY / "injection.csv"
    with detail.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out = summarize(rows)
    summary = SUMMARY / "injection_summary.csv"
    with summary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    return detail, summary


def summarize(rows: list[dict]) -> list[dict]:
    """Recall, and precision against the traps, per method and category from the plant rows."""
    out = []
    for method in sorted({r["method"] for r in rows}):
        mine = [r for r in rows if r["method"] == method]
        runs = {(r["repo"], r["seed"]): r for r in mine}
        for category in [*CATEGORIES, "all"]:
            slop = [r for r in mine if r["kind"] == "slop" and category in (r["category"], "all")]
            traps = [r for r in mine if r["kind"] == "trap" and category in (r["category"], "all")]
            hit = sum(r["removed"] for r in slop)
            wrong = sum(r["removed"] for r in traps)
            out.append(
                {
                    "method": method,
                    "category": category,
                    "planted": len(slop),
                    "removed": hit,
                    "recall": round(hit / len(slop), 3) if slop else "",
                    "traps": len(traps),
                    "traps_removed": wrong,
                    "precision": round(hit / (hit + wrong), 3) if hit + wrong else "",
                    "runs": len(runs),
                    "hidden_changed": sum(bool(r["hidden_changed"]) for r in runs.values()),
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "table", "validate"])
    parser.add_argument("--repos", nargs="+", default=REPOS)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=["cleansweep", *LABELS])
    args = parser.parse_args(argv)
    if args.what == "table":
        print(*table(), sep="\n")
        return 0
    if args.what == "validate":
        for row in validate(args.repos, args.seeds):
            print(json.dumps(row), flush=True)
        return 0
    cfg = load_config(
        {"reviewer": {"scope": "repo"}, "core": {"sandbox": {"aidev_clones": CLONES}}}
    )
    for repo in args.repos:
        for seed in args.seeds:
            name = "toy" if repo == "toy" else repo.replace("/", "__")
            if not (RAW / f"{name}-s{seed}" / "key.json").exists():
                try:
                    prepare(repo, seed, cfg)
                except ValueError as exc:  # nowhere to plant, or no valid draw: left out
                    print(f"skip {repo}: {exc}", flush=True)
                    continue
            for method in args.methods:
                if (RAW / f"{name}-s{seed}" / f"{method}.json").exists():
                    continue
                try:
                    print(json.dumps(run_one(repo, seed, method, cfg)), flush=True)
                except Exception as exc:  # record and go on; a rerun retries it
                    errors = RAW / f"{name}-s{seed}" / "errors"
                    errors.mkdir(exist_ok=True)
                    (errors / f"{method}.txt").write_text(traceback.format_exc())
                    print(f"error {repo} {method}: {type(exc).__name__}: {exc}", flush=True)
    print(*table(), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
