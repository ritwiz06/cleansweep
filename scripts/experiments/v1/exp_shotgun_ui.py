"""Shotgun UI check: does a cleanup change what shotgun's screens and widgets show?

    python scripts/experiments/v1/exp_shotgun_ui.py [--reports FOLDER]

shotgun is a Textual app, and its hidden tests don't draw screens. This opens shotgun at the swept
commit in its AIDev container (Docker, no LLM) and runs
scripts/experiments/v1/shotgun_ui_harness.py there, which mounts every screen and widget of
shotgun.tui that builds without arguments headless (App.run_test) and snapshots its widget tree
and visible text.

Variants: the base (twice, to find snapshots that differ between two identical runs), each
method's final diff from the shotgun sweeps, and each policy's filtered diff from
exp_public_api_policy.py (results/raw/aidev_<policy>/). A variant changes a class when its
snapshot differs from the base's while the class still exists; a class the diff deleted is
counted apart (removed), with whether its name appears anywhere else in the project. Unstable
classes are left out, and a module that stops importing is counted too. Saved snapshots in
results/raw/shotgun_ui/ are reused, so only a missing variant needs Docker.

The shotgun reports default to the scoped AIDev reruns in ../cleansweep-archive
(scripts/experiments/v1/archive_paths.py).

Writes results/raw/shotgun_ui/<variant>.json and results/summary/v1/shotgun_ui.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_paths import archived, check_defaults  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REPORTS = archived("cleansweep-runs-5", "aidev_scoped")
TARGET = "shotgun-sh__shotgun"
METHODS = [
    "cleansweep-gatekeeper",
    "cleansweep-advisory",
    "guard_tests_only",
    "tools_only",
    "one_shot_llm",
]
POLICIES = {
    "public_api": "aidev_public_api",
    "framework": "aidev_framework_rule",
    "final": "aidev_final_policy",
}
HARNESS = Path(__file__).resolve().parent / "shotgun_ui_harness.py"
RAW = ROOT / "results" / "raw" / "shotgun_ui"
OUT = ROOT / "results" / "summary" / "v1" / "shotgun_ui.csv"
FIELDS = [
    "variant",
    "method",
    "policy",
    "applied",
    "classes",
    "rendered",
    "changed",
    "removed",
    "removed_referenced",
    "modules_broken",
    "changed_classes",
    "removed_classes",
]


def variants(reports: Path) -> list[tuple[str, str, str, str]]:
    """(name, method, policy, diff) for each method's final diff and each policy's filtered diff."""
    out = []
    for method in METHODS:
        rep = json.loads((reports / f"{TARGET}__{method}.json").read_text())
        out.append((method, method, "as run", rep["stats"].get("final_diff", "")))
        for policy, folder in POLICIES.items():
            path = ROOT / "results" / "raw" / folder / f"{TARGET}__{method}.json"
            if path.exists():
                diff = json.loads(path.read_text())["filtered_diff"]
                out.append((f"{method}__{policy}", method, policy, diff))
    return out


def snapshot(ws) -> dict:
    subprocess.run(["docker", "cp", str(HARNESS), f"{ws.container}:/tmp/harness.py"], check=True)
    code, out = ws.run(["bash", "-c", "python /tmp/harness.py > /tmp/ui.json"], timeout=3600)
    if code != 0:
        raise RuntimeError(f"harness failed: {out[-500:]}")
    return json.loads(ws.run(["cat", "/tmp/ui.json"], timeout=60)[1])


def compare(base: dict, other: dict, unstable: set[str]) -> dict[str, list[str]]:
    """Classes whose snapshot changed while the class still exists, classes the diff deleted,
    and modules that stopped importing."""
    stable = [n for n in base["classes"] if n not in unstable]
    return {
        "changed": [
            n for n in stable if n in other["classes"] and other["classes"][n] != base["classes"][n]
        ],
        "removed": [n for n in stable if n not in other["classes"]],
        "broken": sorted(set(other["import_errors"]) - set(base["import_errors"])),
    }


def referenced(clone: Path, sha: str, name: str) -> bool:
    """True if the class name appears in a file other than its own definition's."""
    out = subprocess.run(
        ["git", "grep", "-lw", name.rsplit(".", 1)[-1], sha, "--", "*.py"],
        cwd=clone,
        capture_output=True,
        text=True,
    ).stdout
    own = name.rsplit(".", 1)[0].replace(".", "/")
    return any(not line.split(":", 1)[-1].endswith(f"{own}.py") for line in out.splitlines())


def snapshots(rep: dict, reports: Path) -> dict[str, dict | None]:
    """Snapshot per variant: from results/raw/shotgun_ui/ when saved, else run in Docker."""
    wanted = ["base", "base_again", *(name for name, *_ in variants(reports))]
    if all((RAW / f"{n}.json").exists() for n in wanted):
        return {n: json.loads((RAW / f"{n}.json").read_text()) for n in wanted}
    ws = open_workspace(rep["repo_id"], load_config()["core"].get("sandbox"))
    RAW.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict | None] = {}
    try:
        for name in ("base", "base_again"):
            out[name] = snapshot(ws)
            (RAW / f"{name}.json").write_text(json.dumps(out[name], indent=1))
        for name, _, _, diff in variants(reports):
            ws.rollback(ws.base)
            applied = ws.apply_patch(diff) if diff.strip() else True
            out[name] = snapshot(ws) if applied else None
            if out[name] is not None:
                (RAW / f"{name}.json").write_text(json.dumps(out[name], indent=1))
            print(f"{name}: snapshot {'taken' if applied else 'skipped (diff did not apply)'}")
    finally:
        ws.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", default=str(REPORTS), help="folder with the shotgun reports")
    args = parser.parse_args(argv)
    check_defaults("exp_shotgun_ui.py", parser, args, ["--reports"])
    reports = Path(args.reports)
    rep = json.loads((reports / f"{TARGET}__cleansweep-gatekeeper.json").read_text())
    snaps = snapshots(rep, reports)
    base = snaps["base"]
    unstable = {n for n, s in base["classes"].items() if snaps["base_again"]["classes"].get(n) != s}
    rendered = sum("tree" in s for n, s in base["classes"].items() if n not in unstable)
    clone = ROOT / load_config()["data"]["aidev"]["clones"] / TARGET
    sha = rep["repo_id"].rsplit("@", 1)[1]
    print(f"base: {len(base['classes'])} classes, {rendered} render, {len(unstable)} unstable")
    rows = []
    for name, method, policy, _ in variants(reports):
        snap = snaps.get(name)
        found = compare(base, snap, unstable) if snap else {}
        used = [n for n in found.get("removed", []) if referenced(clone, sha, n)]
        rows.append(
            {
                "variant": name,
                "method": method,
                "policy": policy,
                "applied": int(snap is not None),
                "classes": len(base["classes"]),
                "rendered": rendered,
                "changed": len(found["changed"]) if snap else "",
                "removed": len(found["removed"]) if snap else "",
                "removed_referenced": len(used) if snap else "",
                "modules_broken": len(found["broken"]) if snap else "",
                "changed_classes": "; ".join(
                    c.rsplit(".", 1)[-1] for c in found.get("changed", [])
                ),
                "removed_classes": "; ".join(
                    c.rsplit(".", 1)[-1] for c in found.get("removed", [])
                ),
            }
        )
        print(
            f"{name}: changed {rows[-1]['changed']}, removed {rows[-1]['removed']} "
            f"({rows[-1]['removed_referenced']} referenced)"
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
