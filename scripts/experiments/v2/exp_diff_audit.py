"""A blinded diff audit: an independent model reads every kept code edit of the v2 runs and says
whether it changes behavior anyone could observe. Its votes are LLM-judged; every "yes" or
"unsure" is then checked by hand (a targeted test or a close reading of the code) and the check
is recorded with its evidence.

    python scripts/experiments/v2/exp_diff_audit.py run
    python scripts/experiments/v2/exp_diff_audit.py pending
    python scripts/experiments/v2/exp_diff_audit.py table

run: collects the kept edits (status kept, with a diff, not formatting) of the answer-key, SWE-bench
and AIDev runs (results/raw/v2_eval/, with v1's gatekeeper run on each SWE-bench and AIDev target
the team ran), the injected set (results/raw/inject/) and the case studies
(results/raw/case_studies/), and merges identical edits (same project, file and diff). The
auditor is VOYAGER_MODEL_ALT, never the agents' model. It sees the project, the file, the code
around the edit at the commit the run started from, the diff, and where the names the edit
removes appear elsewhere in the project; never the method, the edit's category, the agents'
evidence or verdicts. Each edit is asked 3 times (seeds 0, 1, 2, temperature 0.3, reasoning
off) and the majority decides (no majority: unsure). Resumable: results/raw/diff_audit/
audit.json. A light job: it waits while the 1-minute load average is above the CPU count.
pending: the "yes" and "unsure" edits without a check in results/summary/v2/diff_audit_checks.csv
(edit, verdict wrong | fine, evidence).
table: results/summary/v2/diff_audit.csv, per method: kept code edits, auditor yes / unsure /
no, confirmed wrong edits with a rate and a 95% bootstrap CI over runs, and how many of them every
check missed (the run's hidden checks unchanged or not available).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "v1"))

from exp_collect_v2 import SETS, v1_report  # noqa: E402
from exp_llm_review import PARALLEL, _ask, majority  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.llm.client import get_client  # noqa: E402

RAW = ROOT / "results" / "raw"
OUT = RAW / "diff_audit"
SUMMARY = ROOT / "results" / "summary" / "v2"
CHECKS = SUMMARY / "diff_audit_checks.csv"
CACHE = OUT / "llm_cache.sqlite"
ANSWERS = ("yes", "no", "unsure")
SYSTEM = (
    "You audit edits made to Python projects. For each edit you see the code around it, the "
    "diff, and where the names it removes appear elsewhere in the project. Decide whether the "
    "edit changes behavior that anyone could observe: a user of the program, code that imports "
    "or calls it (also from outside the project, for a library), a script, a test, the package "
    "build or its installed dependencies. Removing code that nothing can reach does not change "
    "behavior; neither does removing a comment or an unused import of a module without side "
    "effects."
)
QUESTION = (
    "Does this edit change behavior anyone could observe? Reply with JSON only: "
    '{"answer": "yes" | "no" | "unsure", "reason": "<one line>"}'
)
DEMO = ROOT / ".cleansweep" / "demo" / "shop_app"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


class Tree:
    """The project as a run found it: a git repository at a commit (with a path prefix), a plain
    folder, or nothing (SWE-bench: the code lives in its container image)."""

    def __init__(self, repo: Path | None, rev: str = "", prefix: str = ""):
        self.repo, self.rev, self.prefix = repo, rev, prefix

    def read(self, path: str) -> str:
        if self.repo is None:
            return ""
        if self.rev:
            return _git(self.repo, "show", f"{self.rev}:{self.prefix}{path}")
        file = self.repo / path
        return file.read_text(errors="replace") if file.is_file() else ""

    def grep(self, name: str) -> list[str]:
        """file:line: text for each line naming name (whole word), in .py and config files."""
        if self.repo is None:
            return []
        if self.rev:
            out = _git(
                self.repo,
                "grep",
                "-n",
                "-w",
                "-F",
                name,
                self.rev,
                "--",
                f"{self.prefix}*.py",
                f"{self.prefix}*.toml",
                f"{self.prefix}*.cfg",
                f"{self.prefix}*.txt",
            )
            lines = [line.split(":", 1)[1] for line in out.splitlines()]
        else:
            out = subprocess.run(
                [
                    "grep",
                    "-rnw",
                    "-F",
                    name,
                    "--include=*.py",
                    "--include=*.toml",
                    "--include=*.cfg",
                    "--include=*.txt",
                    ".",
                ],
                cwd=self.repo,
                capture_output=True,
                text=True,
            ).stdout
            lines = [line.removeprefix("./") for line in out.splitlines()]
        return [line.removeprefix(self.prefix) for line in lines]


def tree_for(repo_id: str, source: Path) -> Tree:
    """Where to read the project a report ran on."""
    if repo_id.startswith("aidev:"):
        full, _, sha = repo_id.removeprefix("aidev:").partition("@")
        name = full.replace("/", "__")
        injected = ROOT / "data" / "raw" / "aidev" / "injected" / name
        if source.parent.parent.name == "inject":
            return Tree(injected, sha)
        clone = ROOT / load_config()["data"]["aidev"]["clones"] / name
        return Tree(clone, sha or "HEAD")
    if repo_id == "local:toy_repo":
        return Tree(ROOT / "tests" / "fixtures" / "toy_repo")
    if repo_id == "local:shop_app":
        return Tree(DEMO)
    if repo_id == "local:repo":  # the injected toy repository of exp_inject.py
        return Tree(source.parent / "repo", "HEAD")
    if repo_id.startswith("local:"):  # this repository, at the commit the case study ran on
        summary = json.loads((source.parent / "summary.json").read_text())
        return Tree(ROOT, summary.get("source_rev") or "HEAD")
    return Tree(None)


def kept_edits(report: dict) -> list[dict]:
    items = {i["item_id"]: i for i in report["plan"]["items"]}
    out = []
    for result in report["results"]:
        item = items.get(result["item_id"], {})
        if result["status"] != "kept" or not result.get("diff") or item.get("category") == "format":
            continue
        unit = item.get("unit") or {}
        out.append(
            {
                "item_id": result["item_id"],
                "category": item.get("category", ""),
                "path": unit.get("path", ""),
                "start": unit.get("start_line") or 0,
                "diff": result["diff"],
            }
        )
    return out


def hidden_of(report: dict) -> int | str:
    hidden = report["stats"].get("hidden") or {}
    if not hidden or hidden.get("applied") is False or hidden.get("behavior_changed") is None:
        return ""
    return int(bool(hidden.get("behavior_changed")))


def runs() -> list[tuple[str, str, str, Path]]:
    """(source, method, run, report path) for every run the audit covers."""
    out = []
    for folder, target_set in SETS.items():
        for path in sorted((RAW / "v2_eval" / folder).glob("*__*__r*.json")):
            name, label, repeat = path.stem.rsplit("__", 2)
            out.append((target_set, label, f"{name}/{repeat}", path))
            if target_set != "answer keys":
                v1 = v1_report(target_set, name)
                if v1 is not None and (target_set, "cleansweep-gatekeeper", name, v1) not in out:
                    out.append((target_set, "cleansweep-gatekeeper", name, v1))
    for path in sorted((RAW / "v2_eval" / "aidev_after124").glob("*__*__r*.json")):
        name, _, repeat = path.stem.rsplit("__", 2)
        out.append(("aidev after #124", "agentic", f"{name}/{repeat}", path))
    for path in sorted((RAW / "inject").glob("*-s*/*.json")):
        if path.name != "key.json":
            out.append(("injected", path.stem, path.parent.name, path))
    for path in sorted((RAW / "case_studies").glob("*/report.json")):
        name = path.parent.name
        summary = path.parent / "summary.json"
        ablation = json.loads(summary.read_text()).get("ablation") if summary.exists() else None
        source = "real-project ablation" if "-abl-" in name else "case studies"
        method = "agentic" + (f"-{ablation}" if ablation else "")
        if "thorough" in name:
            method += " (thorough)"
        out.append((source, method, name, path))
    return out


def _normal(diff: str) -> str:
    return "\n".join(
        line for line in diff.splitlines() if not line.startswith(("index ", "diff --git"))
    )


def collect() -> tuple[dict, list[dict]]:
    """(unique edits by id, occurrences: one row per kept edit in a run)."""
    edits, rows = {}, []
    for source, method, run, path in runs():
        report = json.loads(path.read_text())
        project = report["repo_id"]
        for edit in kept_edits(report):
            key = f"{project}\n{edit['path']}\n{_normal(edit['diff'])}"
            edit_id = hashlib.sha1(key.encode()).hexdigest()[:12]
            edits.setdefault(edit_id, {**edit, "project": project, "report": str(path)})
            rows.append(
                {
                    "edit": edit_id,
                    "source": source,
                    "method": method,
                    "run": run,
                    "category": edit["category"],
                    "hidden_changed": hidden_of(report),
                }
            )
    return edits, rows


def removed_names(diff: str, path: str) -> list[str]:
    names = []
    for line in diff.splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        text = line[1:].strip()
        names += re.findall(r"^(?:async\s+)?(?:def|class)\s+(\w+)", text)
        m = re.match(r"^from\s+\S+\s+import\s+(.+)", text) or re.match(r"^import\s+(.+)", text)
        if m:
            names += [
                p.split()[-1].split(".")[0] for p in m.group(1).strip("()").split(",") if p.strip()
            ]
    if "deleted file mode" in diff:
        names.append(Path(path).stem)
    return [n for n in dict.fromkeys(names) if len(n) >= 3]


def _hunks(diff: str) -> list[tuple[int, int]]:
    return [
        (int(a), int(a) + int(b or 1)) for a, b in re.findall(r"^@@ -(\d+)(?:,(\d+))? ", diff, re.M)
    ]


def view(edit: dict, tree: Tree) -> str:
    """The blinded text the auditor sees for one edit."""
    text = tree.read(edit["path"])
    parts = [f"Project: {edit['project'].split('@')[0]}", f"File: `{edit['path']}`", ""]
    if text:
        lines = text.splitlines()
        spans = _hunks(edit["diff"]) or [(1, 40)]
        a, b = max(1, spans[0][0] - 15), min(len(lines), spans[-1][1] + 15)
        b = min(b, a + 150)
        code = "\n".join(f"{n:>5} {lines[n - 1]}" for n in range(a, b + 1))
        parts += ["Code before the edit:", "```", code, "```", ""]
    parts += ["Diff:", "```diff", edit["diff"][:5000], "```", ""]
    names = removed_names(edit["diff"], edit["path"])
    if tree.repo is None:
        parts.append("Where removed names appear: not searched (the project is not available).")
    else:
        found = []
        for name in names[:6]:
            hits = [h for h in tree.grep(name) if not h.startswith(f"{edit['path']}:")]
            same = [h for h in tree.grep(name) if h.startswith(f"{edit['path']}:")]
            shown = "; ".join(hits[:6]) + (f"; and {len(hits) - 6} more" if len(hits) > 6 else "")
            found.append(
                f"- `{name}`: {len(same)} line(s) in this file; "
                + (f"elsewhere: {shown}" if hits else "nowhere else in the project")
            )
        parts += ["Where removed names appear (before the edit):", *(found or ["- (no names)"])]
    return "\n".join(parts)


def _wait_for_load() -> None:
    while os.getloadavg()[0] > (os.cpu_count() or 4):
        time.sleep(30)


def run_audit() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "audit.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    edits, _ = collect()
    todo = [e for e in sorted(edits) if e not in done]
    random.Random(572).shuffle(todo)
    cfg = load_config()["core"]["llm"]
    llm = get_client({**cfg, "alt": True, "cache_path": str(CACHE)})

    def ask(edit_id: str) -> tuple[str, dict]:
        _wait_for_load()
        edit = edits[edit_id]
        text = view(edit, tree_for(edit["project"], Path(edit["report"])))
        votes = _ask(llm, SYSTEM, text, QUESTION, "answer", ANSWERS)
        answer = majority([v["answer"] for v in votes])
        return edit_id, {"answer": answer, "votes": votes, "view": text, **edit}

    with ThreadPoolExecutor(PARALLEL) as pool:
        for n, (edit_id, record) in enumerate(pool.map(ask, todo), 1):
            done[edit_id] = record
            if n % 20 == 0 or n == len(todo):
                path.write_text(json.dumps(done, indent=1))
                print(f"{n}/{len(todo)} edits audited", flush=True)
    path.write_text(json.dumps(done, indent=1))
    return path


def checks() -> dict[str, dict]:
    if not CHECKS.exists():
        return {}
    with CHECKS.open() as f:
        return {r["edit"]: r for r in csv.DictReader(f)}


def pending() -> list[dict]:
    audit = json.loads((OUT / "audit.json").read_text())
    known = checks()
    return [
        {"edit": e, "answer": r["answer"], "project": r["project"], "path": r["path"]}
        for e, r in sorted(audit.items())
        if r["answer"] != "no" and e not in known
    ]


def _ci(by_run: dict[str, tuple[int, int]], n: int = 2000) -> tuple[float, float]:
    keys = sorted(by_run)
    rng = random.Random(572)
    rates = []
    for _ in range(n):
        pick = [by_run[rng.choice(keys)] for _ in keys]
        kept = sum(k for _, k in pick)
        rates.append(sum(w for w, _ in pick) / kept if kept else 0.0)
    rates.sort()
    return round(rates[int(0.025 * n)], 4), round(rates[int(0.975 * n) - 1], 4)


def table() -> Path:
    audit = json.loads((OUT / "audit.json").read_text())
    known = checks()
    _, rows = collect()
    out = []
    for source, method in sorted({(r["source"], r["method"]) for r in rows}):
        mine = [r for r in rows if (r["source"], r["method"]) == (source, method)]
        answers = [audit.get(r["edit"], {}).get("answer", "") for r in mine]
        wrong = [r for r in mine if known.get(r["edit"], {}).get("verdict") == "wrong"]
        open_ = [
            r
            for r, a in zip(mine, answers, strict=True)
            if a in ("yes", "unsure") and r["edit"] not in known
        ]
        by_run: dict[str, list[int]] = {}
        for r in mine:
            w, k = by_run.get(r["run"], [0, 0])
            by_run[r["run"]] = [w + (r in wrong), k + 1]
        low, high = _ci({k: tuple(v) for k, v in by_run.items()})
        out.append(
            {
                "source": source,
                "method": method,
                "runs": len(by_run),
                "kept_code_edits": len(mine),
                "unique_edits": len({r["edit"] for r in mine}),
                "auditor_yes": answers.count("yes"),
                "auditor_unsure": answers.count("unsure"),
                "auditor_no": answers.count("no"),
                "not_audited": answers.count(""),
                "checks_open": len(open_),
                "confirmed_wrong": len(wrong),
                "wrong_rate": round(len(wrong) / len(mine), 4) if mine else "",
                "ci_low": low,
                "ci_high": high,
                "missed_by_every_check": sum(r["hidden_changed"] != 1 for r in wrong),
            }
        )
    SUMMARY.mkdir(parents=True, exist_ok=True)
    path = SUMMARY / "diff_audit.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "pending", "table"])
    args = parser.parse_args(argv)
    if args.what == "run":
        print(run_audit())
    elif args.what == "pending":
        for row in pending():
            print(json.dumps(row))
    else:
        print(table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
