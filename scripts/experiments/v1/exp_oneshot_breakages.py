"""One-shot breakages: what one_shot_llm changed where SWE-bench hidden behavior changed.

    python scripts/experiments/v1/exp_oneshot_breakages.py [--no-inspect] [--t2 FOLDER]
        [--t2-oneshot FOLDER] [--t2-rerun FOLDER]

Reads the same Tier 1 and Tier 2 reports as exp_collect.py (the Tier 2 folders default to the
run copies' raw reports in ../cleansweep-archive, scripts/experiments/v1/archive_paths.py). For
every one_shot_llm run whose hidden checks changed, it classifies the edits (a deleted file that
tests or code use, an edit to source code, or other) and lists the hidden tests that changed. It
also compares the edit types of one_shot_llm and cleansweep (gatekeeper) over all patches.

Unless --no-inspect, each distinct breaking diff is applied in the patch's workspace (Docker,
no LLM): the edited files are parsed and checked with ruff for undefined names, before and after,
removed functions are looked up in the rest of the project, and deleted files are looked up in
the import graph.

Writes results/summary/oneshot_breakages.csv and oneshot_breakages.md.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_paths import archived, check_defaults  # noqa: E402

from cleansweep.analysis import build_graph  # noqa: E402
from cleansweep.analysis.graph import is_test_file  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "results" / "raw"
# Tier 2 report folders as exp_collect.py reads them; main() takes them from its flags
T2 = {
    "t2": archived("cleansweep-runs", "swebench_t2"),
    "t2_oneshot": archived("cleansweep-runs-2", "swebench_t2_oneshot"),
    "t2_rerun": archived("cleansweep-runs-2", "swebench_t2_rerun"),
}
OUT = ROOT / "results" / "summary" / "oneshot_breakages"
EXCLUDE = ("psf__requests-2317",)
FIELDS = [
    "target_set",
    "target",
    "same_diff_as",
    "files_deleted",
    "deleted_files_used",
    "source_files_edited",
    "lines_added",
    "lines_removed",
    "edit_class",
    "cause",
    "syntax_error_files",
    "new_undefined_names",
    "removed_defs",
    "removed_defs_used_elsewhere",
    "f2p_p2p_failed",
    "patchdiff_changed",
    "visible_new_failures",
    "hidden_tests_failed",
]


def report_path(target_set: str, target: str, method: str) -> Path | None:
    """Where exp_collect.py takes a run from."""
    name = f"{target}__{method}.json"
    if target_set == "swebench_t1":
        folders = [RAW / "swebench_t1"]
    elif method == "one_shot_llm":
        folders = [T2["t2_oneshot"]]
    else:
        folders = [T2["t2"], T2["t2_rerun"]]
    return next((f / name for f in folders if (f / name).exists()), None)


def targets(target_set: str) -> list[str]:
    split = "swebench_tier1.json" if target_set == "swebench_t1" else "swebench_tier2.json"
    entries = json.loads((ROOT / "data" / "splits" / split).read_text())
    found = [f"{e['instance_id']}__{e['agent']}" for e in entries]
    return [t for t in found if not t.startswith(EXCLUDE)]


def diff_files(diff: str) -> list[dict]:
    """One entry per file in a unified diff: path, status, added and removed lines."""
    out = []
    for section in re.split(r"(?m)^(?=diff --git )", diff):
        m = re.match(r"diff --git a/(\S+) b/(\S+)", section)
        if not m:
            continue
        lines = section.splitlines()
        status = "deleted" if "\ndeleted file mode" in section else "modified"
        status = "added" if "\nnew file mode" in section else status
        body = [ln for ln in lines if not ln.startswith(("---", "+++"))]
        out.append(
            {
                "path": m.group(1) if status == "deleted" else m.group(2),
                "status": status,
                "added": sum(ln.startswith("+") for ln in body),
                "removed": sum(ln.startswith("-") for ln in body),
                "removed_defs": _removed_defs(body),
            }
        )
    return out


def _removed_defs(body: list[str]) -> list[str]:
    pattern = r"^[-+]\s*(?:async\s+)?(?:def|class)\s+(\w+)"
    gone = {m.group(1) for ln in body if ln.startswith("-") and (m := re.match(pattern, ln))}
    back = {m.group(1) for ln in body if ln.startswith("+") and (m := re.match(pattern, ln))}
    return sorted(gone - back)


def edit_types(diff: str) -> dict:
    files = diff_files(diff)
    deleted = [f for f in files if f["status"] == "deleted"]
    source = [
        f
        for f in files
        if f["status"] == "modified" and f["path"].endswith(".py") and not is_test_file(f["path"])
    ]
    return {
        "files_deleted": len(deleted),
        "lines_in_deleted_files": sum(f["removed"] for f in deleted),
        "source_files_edited": len(source),
        "source_lines_changed": sum(f["added"] + f["removed"] for f in source),
        "other_files_edited": len(files) - len(deleted) - len(source),
    }


def _syntax_ok(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        return True
    except SyntaxError:
        return False


def _undefined(path: Path) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F821"]
        + ["--output-format", "json", "--no-cache", str(path)],
        capture_output=True,
        text=True,
    )
    found = json.loads(proc.stdout or "[]")
    names = (re.match(r"Undefined name `(.+)`", f["message"]) for f in found)
    return {m.group(1) for m in names if m}


def _used_elsewhere(repo: Path, name: str, skip: set[str]) -> list[str]:
    proc = subprocess.run(
        ["git", "grep", "-l", "-w", name, "--", "*.py"], cwd=repo, capture_output=True, text=True
    )
    return [p for p in proc.stdout.split() if p not in skip]


def inspect(target: str, diff: str, cfg: dict) -> dict:
    """Apply the diff in the patch's workspace and look at what it broke."""
    from cleansweep.sandbox import open_workspace

    instance, agent = target.rsplit("__", 1)
    ws = open_workspace(f"swebench:{instance}:{agent}", {**cfg["core"]["sandbox"], "flaky_runs": 0})
    try:
        repo = Path(ws.path)
        files = diff_files(diff)
        graph = build_graph(ws.path)
        edited = [
            f["path"] for f in files if f["status"] == "modified" and f["path"].endswith(".py")
        ]
        before = {p: _undefined(repo / p) for p in edited}
        if not ws.apply_patch(diff):
            return {"cause": "diff did not apply"}
        bad_syntax = [p for p in edited if not _syntax_ok(repo / p)]
        undefined = sorted({n for p in edited for n in _undefined(repo / p) - before[p]})
        removed = sorted({d for f in files if f["status"] == "modified" for d in f["removed_defs"]})
        touched = {f["path"] for f in files}
        used = sorted(d for d in removed if _used_elsewhere(repo, d, touched))
        deleted_used = [
            f["path"]
            for f in files
            if f["status"] == "deleted"
            and f["path"] in graph.imported_by
            and graph.imported_by[f["path"]] - touched
        ]
        return {
            "syntax_error_files": bad_syntax,
            "new_undefined_names": undefined,
            "removed_defs": removed,
            "removed_defs_used_elsewhere": used,
            "deleted_files_used": deleted_used,
        }
    finally:
        ws.close()


def cause(found: dict) -> tuple[str, str]:
    """(edit class, what broke) from the inspection."""
    if found.get("deleted_files_used"):
        return "deleted a file used by tests or code", "deleted " + ", ".join(
            found["deleted_files_used"]
        )
    if found.get("syntax_error_files"):
        return "edited source code", "rewritten file does not parse (stray quote at the end)"
    if found.get("new_undefined_names"):
        names = ", ".join(found["new_undefined_names"])
        return "edited source code", f"removed an import still in use (undefined: {names})"
    if found.get("removed_defs_used_elsewhere"):
        names = ", ".join(found["removed_defs_used_elsewhere"])
        return "edited source code", f"removed a function used elsewhere ({names})"
    if "cause" in found:
        return "other", found["cause"]
    return "edited source code", "changed logic"


def breakages(do_inspect: bool) -> list[dict]:
    cfg = load_config() if do_inspect else {}
    rows, seen = [], {}
    for target_set in ("swebench_t1", "swebench_t2"):
        for target in targets(target_set):
            path = report_path(target_set, target, "one_shot_llm")
            if path is None:
                continue
            stats = json.loads(path.read_text())["stats"]
            hidden = stats.get("hidden") or {}
            if not hidden.get("behavior_changed"):
                continue
            diff = stats["final_diff"]
            files = diff_files(diff)
            same = seen[diff][0] if diff in seen else ""
            if not same:
                found = inspect(target, diff, cfg) if do_inspect else {}
                seen[diff] = (f"{target_set}/{target}", found)
            found = seen[diff][1]
            edit_class, why = cause(found) if do_inspect else ("", "")
            named = hidden.get("f2p_p2p_changed", [])
            rows.append(
                {
                    "target_set": target_set,
                    "target": target,
                    "same_diff_as": same,
                    "files_deleted": sum(f["status"] == "deleted" for f in files),
                    "deleted_files_used": len(found.get("deleted_files_used", [])),
                    "source_files_edited": sum(
                        f["status"] == "modified" and not is_test_file(f["path"]) for f in files
                    ),
                    "lines_added": sum(f["added"] for f in files),
                    "lines_removed": sum(f["removed"] for f in files),
                    "edit_class": edit_class,
                    "cause": why,
                    "syntax_error_files": "; ".join(found.get("syntax_error_files", [])),
                    "new_undefined_names": "; ".join(found.get("new_undefined_names", [])),
                    "removed_defs": "; ".join(found.get("removed_defs", [])),
                    "removed_defs_used_elsewhere": "; ".join(
                        found.get("removed_defs_used_elsewhere", [])
                    ),
                    "f2p_p2p_failed": len(named),
                    "patchdiff_changed": len(hidden.get("patchdiff_changed", [])),
                    "visible_new_failures": len(hidden.get("visible_new_failures", [])),
                    "hidden_tests_failed": "; ".join(named),
                    "_diff": diff,
                }
            )
    return rows


def comparison() -> list[dict]:
    """Edit types per method over all patches of each tier."""
    out = []
    for target_set in ("swebench_t1", "swebench_t2"):
        for method in ("one_shot_llm", "cleansweep-gatekeeper"):
            totals: dict[str, int] = {}
            runs = changed_source = 0
            for target in targets(target_set):
                path = report_path(target_set, target, method)
                if path is None:
                    continue
                runs += 1
                kinds = edit_types(json.loads(path.read_text())["stats"].get("final_diff", ""))
                changed_source += kinds["source_files_edited"] > 0
                for k, v in kinds.items():
                    totals[k] = totals.get(k, 0) + v
            out.append(
                {
                    "target_set": target_set,
                    "method": method,
                    "patches": runs,
                    "patches_with_source_edits": changed_source,
                    **totals,
                }
            )
    return out


def _example(diff: str, path: str, around: str, limit: int = 14) -> str:
    """Up to `limit` lines of one file's diff, starting a little before `around`."""
    section = next(s for s in re.split(r"(?m)^(?=diff --git )", diff) if f" b/{path}" in s)
    lines = [ln for ln in section.splitlines() if not ln.startswith(("index ", "diff --git"))]
    at = next((i for i, ln in enumerate(lines) if around in ln), 0)
    start = max(at - 4, 2)
    return "\n".join(lines[:2] + lines[start : start + limit - 2])


def write(rows: list[dict], compare: list[dict], examples: list[tuple[str, str, str]]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({k: r[k] for k in FIELDS} for r in rows)
    distinct = [r for r in rows if not r["same_diff_as"]]
    md = [
        "# One-shot breakages on SWE-bench",
        "",
        f"{len(rows)} one_shot_llm runs changed hidden behavior ({len(distinct)} distinct diffs; "
        "the Tier 1 patches are also in Tier 2 and got the same diff).",
        "",
        "| run | edit class | cause | files deleted (used) | F2P/P2P failed | PatchDiff changed |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['target_set']} {r['target']} | {r['edit_class']} | {r['cause']} | "
            f"{r['files_deleted']} ({r['deleted_files_used']}) | {r['f2p_p2p_failed']} | "
            f"{r['patchdiff_changed']} |"
        )
    md += [
        "",
        "## Edit types over all patches",
        "",
        "| target set | method | patches | with source edits | files deleted | lines in deleted "
        "files | source files edited | source lines changed | other files edited |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in compare:
        md.append(
            f"| {c['target_set']} | {c['method']} | {c['patches']} | "
            f"{c['patches_with_source_edits']} | {c['files_deleted']} | "
            f"{c['lines_in_deleted_files']} | {c['source_files_edited']} | "
            f"{c['source_lines_changed']} | {c['other_files_edited']} |"
        )
    md += ["", "## Examples", ""]
    for title, target, text in examples:
        md += [f"**{title}** (`{target}`)", "", "```diff", text, "```", ""]
    OUT.with_suffix(".md").write_text("\n".join(md))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-inspect", action="store_true", help="skip the Docker inspection")
    for key, folder in T2.items():
        parser.add_argument("--" + key.replace("_", "-"), default=str(folder))
    args = parser.parse_args(argv)
    check_defaults("exp_oneshot_breakages.py", parser, args, ["--t2", "--t2-oneshot", "--t2-rerun"])
    T2.update({key: Path(getattr(args, key)) for key in T2})
    rows = breakages(not args.no_inspect)
    by_target = {r["target"]: r["_diff"] for r in rows}
    wanted = [
        (
            "Removed an import the file still uses (sys)",
            "django__django-11133__OpenHands",
            "django/http/response.py",
            "-import sys",
        ),
        (
            "A stray quote after the last line: the file no longer parses",
            "sympy__sympy-11618__LearnByInteract",
            "sympy/geometry/point.py",
            'tolist()[0][:3])"',
        ),
        (
            "Removed a helper and inlined its calls (this file also ends with the stray quote)",
            "scikit-learn__scikit-learn-10844__LearnByInteract",
            "sklearn/metrics/cluster/supervised.py",
            "-def comb2",
        ),
    ]
    examples = [
        (title, target, _example(by_target[target], path, around))
        for title, target, path, around in wanted
        if target in by_target
    ]
    write(rows, comparison(), examples)
    print(f"{len(rows)} breakages -> {OUT.with_suffix('.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
