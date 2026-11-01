"""Reviewer policies on the AIDev sweeps, re-scored without new sweeps.

    python scripts/experiments/v1/exp_public_api_policy.py [--policy public_api|framework|final]
        [--run] [--runs FOLDER ...]

The AIDev run folders default to the run copies' raw reports in ../cleansweep-archive
(scripts/experiments/v1/archive_paths.py).

For every AIDev CleanSweep run (gatekeeper, advisory, guard_tests_only) in main_results.csv,
the applied edits a policy would have kept in the suggest lane are taken out of the final diff:

- public_api: dead-code edits on public names in package modules (reviewer.keep_public_api, auto);
- framework: dead-code and duplicate edits on methods a framework calls by name
  (reviewer.framework_callbacks, on; analysis/frameworks.py);
- final: both, the v1.0 defaults.

The rules are applied to the repository at its head sha (a copy from the local clone): the files
the final diff touches get the final diff, then each dropped edit's own diff in reverse. Lines
removed (excluding format and import edits) are recounted without the dropped edits.

With --run, the hidden checks rerun on each changed diff with the second-model tests cached in
the clone that ran the sweep (Docker, no LLM; a run whose tests aren't cached is skipped), one
JSON per run in results/raw/aidev_<policy>/. A rerun of the same filtered diff under another
policy is reused. A run the policy leaves alone keeps its hidden outcome; a changed run without
a rerun has none yet.

Writes results/summary/v1/aidev_<policy>.csv (one row per run) and .md (per method: as run and
with the policy, mean [95% CI], McNemar and Wilcoxon of the policy against as run).
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_paths import aidev_folders, check_defaults  # noqa: E402
from exp_aidev_summary import load  # noqa: E402
from exp_collect import edit_counts  # noqa: E402

from cleansweep.analysis import build_graph  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.models import CodeUnit  # noqa: E402
from cleansweep.eval.stats import bootstrap_ci, mcnemar, wilcoxon  # noqa: E402
from cleansweep.reviewer.detectors import has_package_metadata, is_public_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "results" / "summary" / "v1" / "main_results.csv"
AIDEV_SPLIT = ROOT / "data" / "splits" / "aidev_repos.json"
# policy -> (raw folder, summary name)
POLICIES = {
    "public_api": ("aidev_public_api", "aidev_public_api_policy"),
    "framework": ("aidev_framework_rule", "aidev_framework_rule"),
    "final": ("aidev_final_policy", "aidev_final_policy"),
}
RAW_DIR = ROOT / "results" / "raw"
OUT_DIR = ROOT / "results" / "summary" / "v1"
TITLES = {
    "public_api": "public-API policy",
    "framework": "framework-callback rule",
    "final": "final policy (public API + framework callbacks)",
}
METHODS = ["cleansweep-gatekeeper", "cleansweep-advisory", "guard_tests_only"]
FIELDS = [
    "target",
    "method",
    "packaging_metadata",
    "dead_code_applied",
    "moved_to_suggest",
    "moved",
    "lines_removed_code",
    "lines_removed_code_policy",
    "hidden_changed",
    "hidden_changed_policy",
    "hidden_rerun",
]


def _git(clone: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=clone, capture_output=True, check=True, **kw)


def export_tree(clone: Path, sha: str, dest: Path) -> None:
    """The repository's files at sha (from the local clone) into dest."""
    tar = dest / "tree.tar"
    tar.write_bytes(_git(clone, "archive", "--format=tar", sha).stdout)
    with tarfile.open(tar) as f:
        f.extractall(dest / "tree", filter="data")
    tar.unlink()


def policy_edits(
    rep: dict, tree: Path, policy: str = "public_api", graph=None
) -> tuple[bool, int, list[dict]]:
    """(packaging metadata, applied dead-code edits, the applied edits the policy would have kept
    in the suggest lane) for one report, with the repository's files in `tree` and, for the
    framework rule, its code graph."""
    items = {i["item_id"]: i for i in rep["plan"]["items"]}
    applied = [
        r
        for r in rep["results"]
        if r["status"] in ("kept", "repaired")
        and (r.get("diff") or "").strip()
        and items.get(r["item_id"], {}).get("category") in ("dead_code", "duplicate")
    ]
    meta = has_package_metadata(str(tree))
    dead = [r for r in applied if items[r["item_id"]]["category"] == "dead_code"]

    def unit(r: dict) -> CodeUnit:
        return CodeUnit(**items[r["item_id"]]["unit"])

    public = {id(r) for r in dead if meta and is_public_api(str(tree), unit(r))}
    framework = {id(r) for r in applied if graph and graph.framework_callback(unit(r).key)}
    keep = {"public_api": public, "framework": framework, "final": public | framework}[policy]
    moved = [{**r, "_unit": items[r["item_id"]]["unit"]} for r in applied if id(r) in keep]
    return meta, len(dead), moved


def filtered_diff(tree: Path, final_diff: str, dropped: list[dict]) -> str | None:
    """The final diff without the dropped edits: a scratch repository with the touched files at
    the base, the final diff applied, then each dropped edit's diff reversed (latest first). An
    edit whose context later edits changed is reversed with fuzz, or, for a deleted function next
    to other deleted ones, put back by position (_reinsert). None when an edit can't be undone, or
    a touched Python file no longer compiles."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        git = ["git", "-c", "user.name=x", "-c", "user.email=x@x"]
        subprocess.run([*git, "init", "-q"], cwd=work, check=True)
        touched = _git(work, "apply", "--numstat", "-", input=final_diff.encode()).stdout
        for line in touched.decode().splitlines():
            path = line.split("\t")[-1]
            src = tree / path
            if src.is_file():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_bytes(src.read_bytes())
        subprocess.run([*git, "add", "-A"], cwd=work, check=True)
        subprocess.run([*git, "commit", "-qm", "base", "--allow-empty"], cwd=work, check=True)
        _git(work, "apply", "-", input=final_diff.encode())
        for r in reversed(dropped):
            if not (_reverse(work, r["diff"]) or _reinsert(work, tree, r)):
                return None
        for path in touched.decode().splitlines():
            path = work / path.split("\t")[-1]
            if path.suffix == ".py" and path.is_file():
                try:
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
                except SyntaxError:
                    return None
        _git(work, "add", "-A")
        return _git(work, "diff", "--cached", "HEAD").stdout.decode()


def _siblings(source: str, name: str) -> list[str] | None:
    """Names of the defs next to `name` ("f" or "Class.f"), in file order, or None."""
    cls, _, func = name.rpartition(".")
    body = ast.parse(source).body
    if cls:
        node = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == cls), None)
        body = node.body if node else []
    names = [
        n.name for n in body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    return names if func in names else None


def _reinsert(work: Path, tree: Path, r: dict) -> bool:
    """Put back a deleted function whose neighbours later edits also deleted: its lines (from the
    edit's diff) go after the nearest earlier def that is still there, else before the next one."""
    hunks = [line for line in r["diff"].splitlines() if line.startswith("@@")]
    added = [line for line in r["diff"].splitlines()[4:] if line.startswith("+")]
    unit = r.get("_unit") or {}
    if len(hunks) != 1 or added or unit.get("kind") != "function":
        return False
    path, name = unit["path"], unit["name"]
    block = [line[1:] for line in r["diff"].splitlines()[4:] if line.startswith("-")]
    order = _siblings((tree / path).read_text(encoding="utf-8"), name)
    current = (work / path).read_text(encoding="utf-8")
    nodes = {
        n.name: n
        for n in ast.walk(ast.parse(current))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    if order is None:
        return False
    cls = name.rpartition(".")[0]
    here = order.index(name.rpartition(".")[2])
    lines = current.splitlines()
    before = [n for n in reversed(order[:here]) if n in nodes]
    after = [n for n in order[here + 1 :] if n in nodes]
    if before:
        at = nodes[before[0]].end_lineno
    elif after:
        node = nodes[after[0]]
        at = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
    elif cls and cls in nodes:
        at = nodes[cls].end_lineno
    else:
        return False
    lines[at:at] = ["", *block] if before else [*block, ""]
    (work / path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _reverse(work: Path, diff: str) -> bool:
    """Reverse one edit's diff in work: exactly, else with up to 3 lines of fuzzy context."""
    exact = ["git", "apply", "-R", "--recount", "-"]
    if subprocess.run(exact, cwd=work, input=diff.encode(), capture_output=True).returncode == 0:
        return True
    fuzzy = ["patch", "-R", "-p1", "-F3", "-f", "-s", "-r", str(work / ".rej")]
    if subprocess.run(
        [*fuzzy, "--dry-run"], cwd=work, input=diff.encode(), capture_output=True
    ).returncode:
        return False
    return subprocess.run(fuzzy, cwd=work, input=diff.encode(), capture_output=True).returncode == 0


def as_run() -> dict[tuple[str, str], dict]:
    """The AIDev CleanSweep rows of main_results.csv (hidden outcome after flaky/overload)."""
    with RESULTS.open() as f:
        rows = [r for r in csv.DictReader(f) if r["target_set"] == "aidev"]
    out = {}
    for r in rows:
        if r["method"] in METHODS:
            ok = r["hidden_flaky"] != "1" and r["overload_suspect"] != "1"
            r["hidden_changed"] = r["hidden_changed"] if ok else ""
            out[(r["target"], r["method"])] = r
    return out


def rerun_hidden(rep: dict, target_id: str, diff: str, cfg: dict) -> dict:
    from cleansweep.eval import run_hidden_checks

    cfg = {**cfg, "exp": {**cfg.get("exp", {}), "hidden_alt_cache": str(rep["_tests"].parent)}}
    return run_hidden_checks(target_id, diff, cfg)


def score(run: bool, policy: str = "public_api", folders: list[Path] | None = None) -> list[dict]:
    rows = as_run()
    folders = aidev_folders() if folders is None else folders
    reports, _ = load([f for f in folders if f.exists()], [])
    by = {(r["_repo"].replace("/", "__"), r["_method"]): r for r in reports}
    heads = {
        e["full_name"].replace("/", "__"): e["head_sha"]
        for e in json.loads(AIDEV_SPLIT.read_text(encoding="utf-8"))
    }
    cfg = load_config()
    clones = ROOT / cfg["data"]["aidev"]["clones"]
    (RAW_DIR / POLICIES[policy][0]).mkdir(parents=True, exist_ok=True)
    out = []
    for target in sorted({t for t, _ in rows}):
        with tempfile.TemporaryDirectory() as tmp:
            tree = graph = None
            for method in METHODS:
                row, rep = rows.get((target, method)), by.get((target, method))
                if row is None or rep is None:
                    continue
                if tree is None:
                    export_tree(clones / target, heads[target], Path(tmp))
                    tree = Path(tmp) / "tree"
                    graph = build_graph(str(tree)) if policy != "public_api" else None
                meta, dead, moved = policy_edits(rep, tree, policy, graph)
                dropped = {r["item_id"] for r in moved}
                counts = edit_counts(
                    {**rep, "results": [r for r in rep["results"] if r["item_id"] not in dropped]}
                )
                hidden = row["hidden_changed"]
                rerun = ""
                if moved:
                    hidden, rerun = _policy_hidden(
                        rep, target, method, heads[target], tree, moved, cfg, run, policy
                    )
                items = {i["item_id"]: i["unit"] for i in rep["plan"]["items"]}
                out.append(
                    {
                        "target": target,
                        "method": method,
                        "packaging_metadata": int(meta),
                        "dead_code_applied": dead,
                        "moved_to_suggest": len(moved),
                        "moved": "; ".join(
                            f"{items[r['item_id']]['path']}::{items[r['item_id']]['name']}"
                            for r in moved
                        ),
                        "lines_removed_code": row["lines_removed_code"],
                        "lines_removed_code_policy": counts["lines_removed_code"],
                        "hidden_changed": row["hidden_changed"],
                        "hidden_changed_policy": hidden,
                        "hidden_rerun": rerun,
                    }
                )
    order = list(rows)  # main_results.csv order, so the intervals match the main table
    return sorted(out, key=lambda r: order.index((r["target"], r["method"])))


def _reused(name: str, diff: str) -> dict | None:
    """The hidden outcome another policy's rerun found for the same filtered diff."""
    for folder, _ in POLICIES.values():
        path = RAW_DIR / folder / name
        if path.exists() and json.loads(path.read_text())["filtered_diff"] == diff:
            return json.loads(path.read_text())["hidden"]
    return None


def _policy_hidden(
    rep, target, method, sha, tree, moved, cfg, run, policy="public_api"
) -> tuple[str, str]:
    """(hidden changed under the policy, how it was found) for a run the policy changes."""
    name = f"{target}__{method}.json"
    path = RAW_DIR / POLICIES[policy][0] / name
    if path.exists():
        hidden = json.loads(path.read_text())["hidden"]
    else:
        diff = filtered_diff(tree, rep["stats"].get("final_diff", ""), moved)
        if diff is None:
            return "", "diff conflict"
        hidden = _reused(name, diff)
        if hidden is None:
            if rep["_tests"] is None:
                return "", "no cached tests"
            if not run:
                return "", "pending"
            hidden = rerun_hidden(rep, f"aidev:{rep['_repo']}@{sha}", diff, cfg)
            print(f"{target} {method}: hidden changed {hidden.get('behavior_changed')}", flush=True)
        path.write_text(json.dumps({"filtered_diff": diff, "hidden": hidden}, indent=1))
    if not hidden.get("available", True) or hidden.get("applied") is False:
        return "", "not applied"
    return int(bool(hidden.get("behavior_changed"))), "rerun"


def summary(rows: list[dict]) -> list[dict]:
    out = []
    for method in METHODS:
        recs = [r for r in rows if r["method"] == method]
        both = [r for r in recs if r["hidden_changed"] != "" and r["hidden_changed_policy"] != ""]
        before = [int(r["hidden_changed"]) for r in both]
        after = [int(r["hidden_changed_policy"]) for r in both]
        lines = [float(r["lines_removed_code"]) for r in recs]
        lines_policy = [float(r["lines_removed_code_policy"]) for r in recs]
        b = sum(a and not p for a, p in zip(before, after, strict=True))
        c = sum(p and not a for a, p in zip(before, after, strict=True))
        _, p_lines = wilcoxon(lines, lines_policy)
        out.append(
            {
                "method": method,
                "repos": len(recs),
                "runs changed by the policy": sum(int(r["moved_to_suggest"]) > 0 for r in recs),
                "edits moved to suggest": sum(int(r["moved_to_suggest"]) for r in recs),
                "with hidden outcome": len(both),
                "hidden changed as run": f"{sum(before)}/{len(both)}",
                "as run (mean, 95% CI)": _ci(before, 2),
                "hidden changed with policy": f"{sum(after)}/{len(both)}",
                "with policy (mean, 95% CI)": _ci(after, 2),
                "McNemar p (policy vs as run)": round(mcnemar(b, c), 4),
                "lines removed as run": _ci(lines, 1),
                "lines removed with policy": _ci(lines_policy, 1),
                "Wilcoxon p (lines)": round(p_lines, 4),
            }
        )
    return out


def _ci(vals: list[float], digits: int) -> str:
    if not vals:
        return "n/a"
    mean, lo, hi = bootstrap_ci(vals)
    return f"{mean:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def _table(rows: list[dict]) -> list[str]:
    cols = list(rows[0])
    return [
        "| " + " | ".join(cols) + " |",
        "|" + "---|" * len(cols),
        *("| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", choices=list(POLICIES), default="public_api")
    parser.add_argument("--run", action="store_true", help="rerun the hidden checks (Docker)")
    parser.add_argument(
        "--runs",
        nargs="+",
        default=[str(f) for f in aidev_folders()],
        help="the AIDev grid folder, then the rerun folders (first folder wins)",
    )
    args = parser.parse_args(argv)
    check_defaults("exp_public_api_policy.py", parser, args, ["--runs"])
    rows = score(args.run, args.policy, [Path(f) for f in args.runs])
    out = OUT_DIR / POLICIES[args.policy][1]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    changed = [r for r in rows if int(r["moved_to_suggest"])]
    lines = [
        f"# AIDev: {TITLES[args.policy]} (re-scored)",
        "",
        "The edits the policy keeps in the suggest lane are taken out of each CleanSweep run's",
        "final diff (see the script's docstring); hidden checks rerun with the cached",
        "second-model tests. Lines removed exclude format and unused-import edits.",
        "",
        *_table(summary(rows)),
        "",
        "## Runs the policy changes",
        "",
        *(_table(changed) if changed else ["None."]),
    ]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n")
    pending = sum(r["hidden_rerun"] in ("pending", "diff conflict") for r in changed)
    print(f"{len(rows)} runs, {len(changed)} changed by the policy, {pending} without a rerun")
    print(out.with_suffix(".md").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
