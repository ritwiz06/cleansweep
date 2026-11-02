"""Slop-injection benchmark: plant known slop and traps into a project at a fixed seed, run each
method on it, and score what it removed.

    python scripts/experiments/v2/exp_inject.py run [--repos toy owner/name ...] [--seeds 1]
        [--methods agentic cleansweep one_shot_llm agentic-<ablation> ...]
    python scripts/experiments/v2/exp_inject.py table

Plants (one each, in three of the project's own package modules chosen by the seed):
- slop the cleanup should remove: a leftover file (scratch_<tag>.py), a dead function, an
  exact duplicate (the same function in two modules, both used), an unused import, a debug
  print (f"{value=}"), a commented-out block, an unused dependency;
- traps it must keep: a near-duplicate (the same function rounding half-even in one module and
  half-up in the other) and a framework callback (an ast.NodeVisitor's visit_Name, which only
  the visitor calls, by name).
A hidden test the methods never see (kept outside the project) checks the planted code's
behavior before and after the method's final diff.

The toy repo is copied as a local project; an AIDev repository becomes an injected clone
(data/raw/aidev/injected/<owner>__<name>: its head plus one commit with the plants) and runs,
like every AIDev target, only inside its container. Every method sees the whole project.
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
    "Fu-Jie/openwebui-extensions",
    "eric-tramel/slop-guard",
    "Usagi-org/ai-goofish-monitor",
    "thomasjjj/Telegram-Snowball-Sampling",
    "wkentaro/imgviz",
    "trailofbits/dropkit",
    "gotalab/skillport",
    "curvedinf/wove",
    "Human-Agent-Society/CORAL",
]
METHODS = ["agentic", "cleansweep", "one_shot_llm"]  # the default comparison
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


def inject(root: Path, seed: int) -> dict:
    """Plant the slop and the traps; return the key (what was planted where)."""
    rng = random.Random(seed)
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
    name = next(d for d in DEPS if d not in taken.lower())
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
    """(target, the injected tree, its key) for the toy repo or an AIDev repository."""
    from cleansweep.data import load_repos
    from cleansweep.data.swebench import data_path

    name = "toy" if repo == "toy" else repo.replace("/", "__")
    folder = RAW / f"{name}-s{seed}"
    if repo == "toy":
        tree = folder / "repo"
        if tree.exists():
            shutil.rmtree(tree)
        _git_tree(ROOT / "tests" / "fixtures" / "toy_repo", tree)
        key = inject(tree, seed)
        _commit(tree, "plants")
        target = str(tree)
    else:
        ref = next(r for r in load_repos() if r.repo_id.removeprefix("aidev:") == repo)
        clone = data_path(cfg["data"]["aidev"]["clones"]) / name
        tree = data_path(CLONES) / name
        if tree.exists():
            shutil.rmtree(tree)
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.Popen(
                ["git", "archive", ref.head_sha], cwd=clone, stdout=subprocess.PIPE
            )
            subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, check=True)
            archive.wait()
            _git_tree(Path(tmp), tree)
        key = inject(tree, seed)
        sha = _commit(tree, "plants")
        target = f"aidev:{repo}@{sha}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "key.json").write_text(json.dumps({**key, "target": target}, indent=1))
    (folder / "hidden").mkdir(exist_ok=True)
    (folder / "hidden" / "test_planted.py").write_text(key["hidden_test"])
    return target, tree, key


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


def final_tree(tree: Path, final_diff: str) -> tuple[Path, bool]:
    """A temporary copy of the injected tree with the final diff applied."""
    tmp = Path(tempfile.mkdtemp(prefix="cs_inject_"))
    subprocess.run(["git", "clone", "-q", str(tree), str(tmp / "t")], check=True)
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
    label, judge, agents = resolve("cleansweep-gatekeeper" if method == "cleansweep" else method)
    if agents:
        cfg = {**cfg, "core": {**cfg["core"], "agents": {**cfg["core"]["agents"], **agents}}}
    if judge:
        os.environ["CLEANSWEEP_JUDGE_MODE"] = judge
    else:
        os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    t0 = time.time()
    cfg = {**cfg, "agent_out": str(folder / f"{method}_run")}
    report = run_sweep(target, cfg, label)
    minutes = round((time.time() - t0) / 60, 2)
    diff = report.stats.get("final_diff", "")
    after, applied = final_tree(tree, diff)
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
    summary = SUMMARY / "injection_summary.csv"
    with summary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    return detail, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "table"])
    parser.add_argument("--repos", nargs="+", default=REPOS)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=["cleansweep", *LABELS])
    args = parser.parse_args(argv)
    if args.what == "table":
        print(*table(), sep="\n")
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
                except ValueError as exc:  # nowhere to plant: the repository is left out
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
