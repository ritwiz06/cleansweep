"""Which one-shot diffs fail a compile check: the one_shot_compile variant, from existing data.

    python scripts/exp_oneshot_compile.py

one_shot_compile is one_shot_llm plus a compile check that discards the whole diff when a
rewritten .py file doesn't compile. No LLM and no new sweep:

- SWE-bench Tier 1 and Tier 2: the Guard's own compile step from exp_guard_on_oneshot.py
  (results/summary/guard_on_oneshot.csv), which compiled the changed files in the instance's
  container. A run blocked at "compile" fails; a run with no edits has nothing to compile.
- AIDev: each one_shot_llm run's final diff is applied to the repository's files at its head sha
  (the local clone, no Docker) and the rewritten .py files are compiled with this Python (3.11,
  as in the AIDev containers).

Writes results/summary/oneshot_compile.csv: one row per one_shot_llm run.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exp_oneshot_breakages import diff_files, report_path, targets  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GUARD_CSV = ROOT / "results" / "summary" / "guard_on_oneshot.csv"
OUT = ROOT / "results" / "summary" / "oneshot_compile.csv"
AIDEV_SPLIT = ROOT / "data" / "splits" / "aidev_repos.json"
# first folder wins, as in exp_collect.py
AIDEV_FOLDERS = [
    ROOT.parent / "cleansweep-runs-3" / "results" / "raw" / "aidev_sweeps",
    ROOT.parent / "cleansweep-runs-5" / "results" / "raw" / "aidev_scoped",
]
FIELDS = ["target_set", "target", "files_compiled", "compile_failed", "source", "errors"]


def compile_failures(files: dict[str, str]) -> list[str]:
    """'path: message' for each .py file whose text doesn't compile."""
    out = []
    for path, text in sorted(files.items()):
        if not path.endswith(".py"):
            continue
        try:
            compile(text, path, "exec")
        except (SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", "?")
            out.append(f"{path}: {getattr(exc, 'msg', str(exc))} (line {line})")
    return out


def rewritten_files(clone: Path, sha: str, diff: str) -> dict[str, str]:
    """The text of each file the diff modifies, after the diff, from the clone at sha."""
    paths = [f["path"] for f in diff_files(diff) if f["status"] == "modified"]
    if not paths:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        for path in paths:
            text = subprocess.run(
                ["git", "show", f"{sha}:{path}"],
                cwd=clone,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            (Path(tmp) / path).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / path).write_text(text, encoding="utf-8")
        # only the modified files are here: the diff's deletions are left out
        sections = re.split(r"(?m)^(?=diff --git )", diff)
        mods = "".join(
            s for s in sections if any(s.startswith(f"diff --git a/{p} ") for p in paths)
        )
        subprocess.run(
            ["git", "apply", "-"], cwd=tmp, input=mods, text=True, check=True, capture_output=True
        )
        return {p: (Path(tmp) / p).read_text(encoding="utf-8") for p in paths}


def swebench_rows() -> list[dict]:
    blocked = {}
    with GUARD_CSV.open() as f:
        for r in csv.DictReader(f):
            blocked[(r["target_set"], r["target"])] = r["check"] == "compile"
    rows = []
    for target_set in ("swebench_t1", "swebench_t2"):
        for target in targets(target_set):
            path = report_path(target_set, target, "one_shot_llm")
            if path is None:
                continue
            diff = json.loads(path.read_text())["stats"].get("final_diff", "")
            failed = blocked.get((target_set, target))
            if failed is None and diff.strip():
                continue  # edits the Guard never checked: no outcome
            py = [f for f in diff_files(diff) if f["status"] == "modified"]
            rows.append(
                {
                    "target_set": target_set,
                    "target": target,
                    "files_compiled": sum(f["path"].endswith(".py") for f in py),
                    "compile_failed": int(bool(failed)),
                    "source": "guard_on_oneshot",
                    "errors": "",
                }
            )
    return rows


def aidev_rows() -> list[dict]:
    clones = ROOT / load_config()["data"]["aidev"]["clones"]
    heads = {
        r["full_name"].replace("/", "__"): r["head_sha"]
        for r in json.loads(AIDEV_SPLIT.read_text(encoding="utf-8"))
    }
    seen, rows = set(), []
    for folder in AIDEV_FOLDERS:
        for path in sorted(folder.glob("*__*__one_shot_llm.json")):
            target = path.name.removesuffix("__one_shot_llm.json")
            if target in seen or target not in heads:
                continue
            seen.add(target)
            diff = json.loads(path.read_text())["stats"].get("final_diff", "")
            files = rewritten_files(clones / target, heads[target], diff)
            errors = compile_failures(files)
            rows.append(
                {
                    "target_set": "aidev",
                    "target": target,
                    "files_compiled": sum(p.endswith(".py") for p in files),
                    "compile_failed": int(bool(errors)),
                    "source": "local clone",
                    "errors": "; ".join(errors),
                }
            )
    return rows


def main() -> int:
    rows = swebench_rows() + aidev_rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    for target_set in ("swebench_t1", "swebench_t2", "aidev"):
        part = [r for r in rows if r["target_set"] == target_set]
        failed = sum(r["compile_failed"] for r in part)
        print(f"{target_set}: {len(part)} one-shot runs, {failed} fail the compile check")
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
