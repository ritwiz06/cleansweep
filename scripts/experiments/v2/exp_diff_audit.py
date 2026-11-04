"""A blinded diff audit: an independent model reads every kept code edit of the v2 runs and says
whether it changes behavior anyone could observe. Its votes are LLM-judged; every "yes" or
"unsure" is then checked (a targeted test, the UI check, a rule, or a close reading of the code)
and the check is recorded with its evidence, a verdict under the rubric (docs/experiments.md) and
the kind of edit.

    python scripts/experiments/v2/exp_diff_audit.py run
    python scripts/experiments/v2/exp_diff_audit.py auto
    python scripts/experiments/v2/exp_diff_audit.py pending
    python scripts/experiments/v2/exp_diff_audit.py match > matched.jsonl
    python scripts/experiments/v2/exp_diff_audit.py show EDIT [EDIT ...]
    python scripts/experiments/v2/exp_diff_audit.py record --input checks.jsonl
    python scripts/experiments/v2/exp_diff_audit.py table
    python scripts/experiments/v2/exp_diff_audit.py sheet [--path PATH]
    python scripts/experiments/v2/exp_diff_audit.py kappa [--path PATH]

run: collects the kept edits (status kept, with a diff, not formatting) of the answer-key, SWE-bench
and AIDev runs (results/raw/v2_eval/, with v1's gatekeeper run on each SWE-bench and AIDev target
the team ran), the injected set (results/raw/inject/) and the case studies the results report plus
the real-project ablation (results/raw/case_studies/), and merges identical edits (same project,
file and diff). The auditor is VOYAGER_MODEL_ALT, never the agents' model. It sees the project, the
file, the code around the edit at the commit the run started from, the diff, and where the names the
edit removes appear elsewhere in the project; never the method, the edit's category, the agents'
evidence or verdicts. Each edit is asked 3 times (seeds 0, 1, 2, temperature 0.3, reasoning off) and
the majority decides (no majority: unsure). Resumable: results/raw/diff_audit/audit.json. A light
job: it waits while the 1-minute load average is above the CPU count.
auto: checks the flagged edits two rules settle without reading: on the injected set, an edit
whose removed lines are all planted lines and that adds nothing is fine when it removes planted
slop and wrong when it removes a trap (the benchmark's key); on SWE-bench, deleting a file the
coding agent's patch created is fine.
pending: the "yes" and "unsure" edits of the runs above without a check in diff_audit_checks.csv
(edit, verdict wrong | debatable | fine, evidence, checked_by, kind).
match: for each pending edit that makes the same change as a checked one (same repository, file,
removed and added lines, and the class or function each hunk sits in), the earlier check as a JSON
line; a rule's tier carries over, a test's does not (it ran on the other edit). The edits left to
read go to stderr. show: the pending edits to read, with where they occur and one auditor vote.
record: merges hand-read checks (JSON lines: edit, verdict, evidence, and kind unless fine;
checked_by defaults to reading, LLM-judged) from --input or stdin into diff_audit_checks.csv.
table: results/summary/v2/diff_audit.csv, per target set and method: kept code edits, auditor yes
/ unsure / no, wrong edits in two tiers (confirmed: a targeted test, the UI check or a rule;
reading: LLM-judged), debatable and fine edits, the wrong rate of all tiers and of the confirmed
tier with 95% bootstrap CIs over runs, and how many wrong edits every check missed (the run's
hidden checks unchanged or not available); and diff_audit_types.csv, the wrong and debatable
edits of each method by kind.
sheet: a calibration sheet for a person: 20 checks drawn at random (seed 572), each with the
blinded view the auditor saw and an empty verdict to fill in under the rubric. kappa: Cohen's
kappa between the filled-in verdicts and the recorded ones.
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
from exp_llm_review import PARALLEL, _ask, cohen, majority  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.llm.client import get_client  # noqa: E402

RAW = ROOT / "results" / "raw"
OUT = RAW / "diff_audit"
SUMMARY = ROOT / "results" / "summary" / "v2"
CHECKS = SUMMARY / "diff_audit_checks.csv"
CACHE = OUT / "llm_cache.sqlite"
SHEET = ROOT / ".notes" / "report" / "audit_calibration_sheet.md"
# the case-study runs the results report; the others were superseded (first tries, killed runs)
CASE_STUDIES = {
    "cleansweep-safe-3b",
    "cleansweep-thorough",
    "slop-guard-safe-3b",
    "slop-guard-thorough",
    "skill-seekers-safe",
    "skill-seekers-thorough",
    "shotgun-safe",
    "telegram-safe",
    "telegram-thorough",
}
DEPENDENCY_FILES = ("requirements", "pyproject.toml", "setup.cfg", "setup.py")
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
            # split on newlines only: a matched line can hold a form feed or a carriage return
            lines = [line.split(":", 1)[1] for line in out.split("\n") if ":" in line]
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
            lines = [line.removeprefix("./") for line in out.split("\n") if line]
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
        if name not in CASE_STUDIES and "-abl-" not in name:
            continue
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


def edit_key(project: str, path: str, diff: str) -> str:
    """The audit's id of an edit: the same project, file and diff give the same id."""
    key = f"{project}\n{path}\n{_normal(diff)}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def collect() -> tuple[dict, list[dict]]:
    """(unique edits by id, occurrences: one row per kept edit in a run)."""
    edits, rows = {}, []
    for source, method, run, path in runs():
        report = json.loads(path.read_text())
        project = report["repo_id"]
        for edit in kept_edits(report):
            edit_id = edit_key(project, edit["path"], edit["diff"])
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


def _dependency(line: str, path: str) -> list[str]:
    """The package a dependency line names, spelled as code would import it."""
    pattern = r"^([A-Za-z][\w.-]*)" if "requirements" in path else r"^[\"']([A-Za-z][\w.-]*)"
    return [n.lower().replace("-", "_") for n in re.findall(pattern, line)]


def removed_names(diff: str, path: str) -> list[str]:
    names = []
    for line in diff.splitlines():
        if not line.startswith("-") or line.startswith("---"):
            continue
        text = line[1:].strip()
        names += re.findall(r"^(?:async\s+)?(?:def|class)\s+(\w+)", text)
        if Path(path).name.startswith(DEPENDENCY_FILES):
            names += _dependency(text, path)
            continue
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


CHECK_FIELDS = ["edit", "verdict", "evidence", "checked_by", "kind"]
VERDICTS = ("wrong", "debatable", "fine")
# what a wrong or debatable edit did (docs/experiments.md, the diff audit's rubric)
KINDS = (
    "dynamic handler or stub",
    "public name",
    "changed logic",
    "deleted file",
    "dependency",
    "other",
)
CONFIRMED = {"targeted test", "UI check", "rule: injection key", "rule: agent patch"}
EVIDENCE = {
    "wrong": "removes a planted trap (the benchmark's key)",
    "fine": "removes planted slop only (the benchmark's key)",
}


def _lines(diff: str, sign: str) -> list[str]:
    head = sign * 3
    return [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith(sign) and not line.startswith(head) and line[1:].strip()
    ]


def plant_lines(key: dict) -> tuple[set[str], set[str]]:
    """(the lines of the planted slop, the distinctive lines of the two traps), stripped, from
    exp_inject.py's templates and the key."""
    tag = key["tag"]
    slop = {
        f'"""Trying out the {tag} totals; not used anywhere."""',
        "values = [1, 2, 3]",
        "print(sum(values))",
        f"def _unused_{tag}(items):",
        "total = 0",
        "for item in items:",
        "total += len(str(item))",
        "return total",
        'print(f"{value=}")',
        f"# result = describe_{tag}(2, verbose=True)",
        "# if result:",
        "#     print(result)",
    }
    for plant in key["plants"]:
        if plant["category"] in ("unused_import", "unused_dependency"):
            slop.add(plant["marker"].strip().strip(","))
    traps = {
        "def visit_Name(self, node):",
        "self.names += 1",
        f"def scale_{tag}(values, factor=100):",
        f"def scale_{tag}_v2(values, factor=100):",
        "out.append(round(value * factor) / factor)",
        "out.append(int(value * factor + 0.5) / factor)",
    }
    return slop, traps


def plant_rule(diff: str, slop: set[str], traps: set[str]) -> str:
    """wrong when the edit removes a trap's line; fine when it removes planted slop only (a line,
    or a planted dependency taken out of a line) and adds nothing but `pass`; "" when reading is
    needed."""
    removed = {line.strip(",") for line in _lines(diff, "-")}
    added = {line.strip(",") for line in _lines(diff, "+")} - {"pass"}
    if removed & traps:
        return "wrong"
    deps = [s.replace(" ", "") for s in slop if ">=" in s]
    for line in sorted(removed - slop):
        rest = line.replace(" ", "")
        for dep in deps:
            rest = rest.replace("," + dep, "").replace(dep + ",", "").replace(dep, "")
        match = next((a for a in added if a.replace(" ", "") == rest), None)
        if match is not None and rest != line.replace(" ", ""):
            removed.discard(line)  # the same line with a planted dependency taken out
            added.discard(match)
    if removed <= slop and not added and _lines(diff, "-"):
        return "fine"
    return ""


def trap_kind(diff: str) -> str:
    """The kind of a removed trap: the NodeVisitor callback, or the near-duplicate pair that
    rounds differently."""
    visitor = {"def visit_Name(self, node):", "self.names += 1"}
    return "dynamic handler or stub" if visitor & set(_lines(diff, "-")) else "changed logic"


def agent_created(project: str) -> set[str]:
    """Files the coding agent's patch created, for a "swebench:<instance>:<agent>" target."""
    from cleansweep.data import load_agent_patches

    _, instance, agent = project.split(":", 2)
    found = [p for p in load_agent_patches([agent]) if p.instance_id == instance]
    if not found:
        return set()
    return set(re.findall(r"^diff --git a/\S+ b/(\S+)\nnew file mode", found[0].patch, re.M))


def auto() -> int:
    """Add the checks the two rules settle; return how many were added."""
    audit = json.loads((OUT / "audit.json").read_text())
    known = checks()
    rows, plants, created = [], {}, {}
    for edit_id, record in sorted(audit.items()):
        if record["answer"] == "no" or edit_id in known:
            continue
        diff, report = record["diff"], Path(record["report"])
        if report.parent.parent.name == "inject":
            if report.parent not in plants:
                plants[report.parent] = plant_lines(
                    json.loads((report.parent / "key.json").read_text())
                )
            verdict = plant_rule(diff, *plants[report.parent])
            if verdict:
                rows.append(
                    {
                        "edit": edit_id,
                        "verdict": verdict,
                        "evidence": EVIDENCE[verdict],
                        "checked_by": "rule: injection key",
                        "kind": trap_kind(diff) if verdict == "wrong" else "",
                    }
                )
        elif record["project"].startswith("swebench:") and "deleted file mode" in diff:
            project = record["project"]
            if project not in created:
                created[project] = agent_created(project)
            if record["path"] in created[project]:
                rows.append(
                    {
                        "edit": edit_id,
                        "verdict": "fine",
                        "evidence": "deletes a file the coding agent's patch created",
                        "checked_by": "rule: agent patch",
                        "kind": "",
                    }
                )
    write_checks([*known.values(), *rows])
    return len(rows)


def write_checks(rows: list[dict]) -> None:
    SUMMARY.mkdir(parents=True, exist_ok=True)
    with CHECKS.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CHECK_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["edit"]))


def checks() -> dict[str, dict]:
    if not CHECKS.exists():
        return {}
    with CHECKS.open() as f:
        return {r["edit"]: r for r in csv.DictReader(f)}


def pending() -> list[dict]:
    audit = json.loads((OUT / "audit.json").read_text())
    edits, _ = collect()
    known = checks()
    return [
        {"edit": e, "answer": r["answer"], "project": r["project"], "path": r["path"]}
        for e, r in sorted(audit.items())
        if r["answer"] != "no" and e in edits and e not in known
    ]


def _change(diff: str) -> tuple[str, ...]:
    return tuple(x for x in diff.splitlines() if x[:1] in "+-" and not x.startswith(("+++", "---")))


def _context(diff: str, path: str) -> tuple[str, ...]:
    """The class or function each hunk sits in (Python files): the same lines removed in another
    class are another change."""
    if not path.endswith(".py"):
        return ()
    return tuple(m.strip() for m in re.findall(r"^@@ [^@]+ @@(.*)$", diff, re.M))


def _same(edit: dict) -> tuple:
    repo = re.sub(r"@.*$", "", edit["project"])
    return repo, edit["path"], _change(edit["diff"]), _context(edit["diff"], edit["path"])


def match(edits: dict, audit: dict, known: dict) -> tuple[list[dict], list[str]]:
    """(checks carried to pending edits that make the same change as a checked edit, the pending
    edits left to read)."""
    index: dict[tuple, list[tuple[str, dict]]] = {}
    for edit_id, check in known.items():
        edit = edits.get(edit_id) or audit.get(edit_id)
        if edit:
            index.setdefault(_same(edit), []).append((edit_id, check))
    found, left = [], []
    for edit_id, rec in sorted(audit.items()):
        if rec["answer"] == "no" or edit_id in known or edit_id not in edits:
            continue
        prior = index.get(_same(edits[edit_id]), [])
        if len({check["verdict"] for _, check in prior}) != 1:
            left.append(edit_id)  # no earlier check, or earlier checks that disagree
            continue
        root, check = prior[0]
        evidence = check["evidence"]
        copied = re.match(r"the same change as (\w{12}) \(.*?\): (.*)", evidence, re.S)
        if copied:
            root, evidence = copied.groups()
        rule = check["checked_by"].startswith("rule:")
        found.append(
            {
                "edit": edit_id,
                "verdict": check["verdict"],
                "evidence": f"the same change as {root} (same file, same removed and added lines; "
                f"another seed or run): {evidence}",
                "checked_by": check["checked_by"] if rule else "reading (LLM-judged)",
                "kind": check.get("kind", ""),
            }
        )
    return found, left


def record(known: dict, lines: list[str]) -> list[dict]:
    """The checks with the given JSON lines merged in."""
    rows = dict(known)
    for line in lines:
        if not line.strip():
            continue
        new = json.loads(line)
        if new["verdict"] not in VERDICTS:
            raise ValueError(f"{new['edit']}: unknown verdict {new['verdict']!r}")
        if new["verdict"] != "fine" and new.get("kind") not in KINDS:
            raise ValueError(f"{new['edit']}: a {new['verdict']} check needs a kind")
        rows[new["edit"]] = {
            "edit": new["edit"],
            "verdict": new["verdict"],
            "evidence": new["evidence"],
            "checked_by": new.get("checked_by", "reading (LLM-judged)"),
            "kind": new.get("kind", ""),
        }
    return list(rows.values())


def show(edit_ids: list[str], limit: int = 3000) -> str:
    """The edits as a reader needs them: where they occur, one auditor vote, the diff."""
    edits, rows = collect()
    audit = json.loads((OUT / "audit.json").read_text())
    out = []
    for edit_id in edit_ids:
        edit = edits[edit_id]
        where = sorted({(r["source"], r["method"], r["run"]) for r in rows if r["edit"] == edit_id})
        out.append(f"#### {edit_id} {edit['project']} {edit['path']} [{edit['category']}]")
        out.append("   in: " + "; ".join(f"{s}/{m}/{r}" for s, m, r in where)[:600])
        for vote in audit.get(edit_id, {}).get("votes", [])[:1]:
            out.append(f"   auditor: {str(vote)[:400]}")
        out.append(edit["diff"][:limit])
    return "\n".join(out)


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


def tier(check: dict) -> str:
    """confirmed (a targeted test, the UI check or a rule) or reading (LLM-judged)."""
    return "confirmed" if check.get("checked_by") in CONFIRMED else "reading"


def _by_run(mine: list[dict], hits: list[dict]) -> dict[str, tuple[int, int]]:
    """run -> (hits, kept code edits)."""
    hit = {id(r) for r in hits}
    out: dict[str, tuple[int, int]] = {}
    for r in mine:
        h, k = out.get(r["run"], (0, 0))
        out[r["run"]] = (h + (id(r) in hit), k + 1)
    return out


def method_row(mine: list[dict], audit: dict, known: dict) -> dict:
    """The table's numbers for one method's kept code edits (rows of collect())."""
    answers = [audit.get(r["edit"], {}).get("answer", "") for r in mine]
    verdict = [known.get(r["edit"], {}).get("verdict", "") for r in mine]
    wrong = [r for r, v in zip(mine, verdict, strict=True) if v == "wrong"]
    confirmed = [r for r in wrong if tier(known[r["edit"]]) == "confirmed"]
    fine = [
        r
        for r, a, v in zip(mine, answers, verdict, strict=True)
        if v == "fine" or (a == "no" and not v)
    ]
    flagged = zip(mine, answers, verdict, strict=True)
    open_ = [r for r, a, v in flagged if a in ("yes", "unsure") and not v]
    low, high = _ci(_by_run(mine, wrong))
    c_low, c_high = _ci(_by_run(mine, confirmed))
    return {
        "runs": len({r["run"] for r in mine}),
        "kept_code_edits": len(mine),
        "unique_edits": len({r["edit"] for r in mine}),
        "auditor_yes": answers.count("yes"),
        "auditor_unsure": answers.count("unsure"),
        "auditor_no": answers.count("no"),
        "not_audited": answers.count(""),
        "checks_open": len(open_),
        "wrong": len(wrong),
        "wrong_confirmed": len(confirmed),
        "wrong_reading": len(wrong) - len(confirmed),
        "debatable": verdict.count("debatable"),
        "fine": len(fine),
        "wrong_rate": round(len(wrong) / len(mine), 4) if mine else "",
        "ci_low": low,
        "ci_high": high,
        "confirmed_rate": round(len(confirmed) / len(mine), 4) if mine else "",
        "confirmed_ci_low": c_low,
        "confirmed_ci_high": c_high,
        "missed_by_every_check": sum(r["hidden_changed"] != 1 for r in wrong),
        "confirmed_missed": sum(r["hidden_changed"] != 1 for r in confirmed),
    }


def kind_counts(rows: list[dict], known: dict) -> list[dict]:
    """The wrong and debatable kept code edits per target set, method, verdict and kind."""
    counts: dict[tuple, list] = {}
    for r in rows:
        check = known.get(r["edit"])
        if not check or check["verdict"] not in ("wrong", "debatable"):
            continue
        key = (r["source"], r["method"], check["verdict"], check.get("kind") or "other")
        n, confirmed, unique = counts.setdefault(key, [0, 0, set()])
        counts[key] = [n + 1, confirmed + (tier(check) == "confirmed"), unique | {r["edit"]}]
    return [
        {
            "source": s,
            "method": m,
            "verdict": v,
            "kind": k,
            "kept_code_edits": n,
            "confirmed": c,
            "unique_edits": len(u),
        }
        for (s, m, v, k), (n, c, u) in sorted(counts.items())
    ]


def _write(path: Path, rows: list[dict]) -> Path:
    SUMMARY.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def table() -> Path:
    audit = json.loads((OUT / "audit.json").read_text())
    known = checks()
    _, rows = collect()
    out = []
    for source, method in sorted({(r["source"], r["method"]) for r in rows}):
        mine = [r for r in rows if (r["source"], r["method"]) == (source, method)]
        out.append({"source": source, "method": method, **method_row(mine, audit, known)})
    _write(SUMMARY / "diff_audit_types.csv", kind_counts(rows, known))
    return _write(SUMMARY / "diff_audit.csv", out)


SHEET_HEAD = """# Diff audit calibration sheet

Each section below is one kept code edit as the auditor saw it: the project, the file, the code
before the edit, the diff, and where the removed names appear. The method that made it and the
recorded verdict are hidden. Give each a verdict in the table at the end, using the rubric:

- wrong: changes behavior that something in the project or its users can actually trigger
- debatable: removes code reachable only from outside the project (a public name nothing in the
  project calls, a handler or stub a framework might call), or the intent is unclear
- fine: no observable change

Then run `python scripts/experiments/v2/exp_diff_audit.py kappa`.
"""


def sheet(path: Path = SHEET, n: int = 20) -> Path:
    """Write the calibration sheet: n checks drawn at random (seed 572), blinded."""
    audit = json.loads((OUT / "audit.json").read_text())
    edits, _ = collect()
    pool = sorted(e for e in checks() if e in edits and e in audit)
    picked = random.Random(572).sample(pool, n)
    parts = [SHEET_HEAD]
    for i, edit in enumerate(picked, 1):
        parts += [f"## {i}. edit {edit}", "", audit[edit]["view"], ""]
    parts += ["## Verdicts", "", "| # | edit | verdict | note |", "|---|---|---|---|"]
    parts += [f"| {i} | {edit} |  |  |" for i, edit in enumerate(picked, 1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n")
    return path


def sheet_verdicts(text: str) -> dict[str, str]:
    """edit -> the verdict filled in on a calibration sheet (rows left empty are skipped)."""
    out = {}
    for m in re.finditer(r"^\|\s*\d+\s*\|\s*([0-9a-f]{12})\s*\|\s*(\w*)\s*\|", text, re.M):
        if m.group(2).lower() in VERDICTS:
            out[m.group(1)] = m.group(2).lower()
    return out


def kappa(path: Path = SHEET) -> dict:
    """Cohen's kappa between a person's verdicts on the sheet and the recorded checks."""
    filled = sheet_verdicts(path.read_text()) if path.exists() else {}
    known = checks()
    pairs = [(v, known[e]["verdict"]) for e, v in filled.items() if e in known]
    human = [h for h, _ in pairs]
    recorded = [r for _, r in pairs]
    agree = sum(h == r for h, r in pairs)
    return {
        "filled": len(pairs),
        "agreement": round(agree / len(pairs), 3) if pairs else None,
        "kappa": cohen(human, recorded),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = ["run", "auto", "pending", "match", "show", "record", "table", "sheet", "kappa"]
    parser.add_argument("what", choices=what)
    parser.add_argument("edits", nargs="*", help="show: the edits to print")
    parser.add_argument("--path", type=Path, default=SHEET, help="the calibration sheet")
    parser.add_argument("--input", type=Path, help="record: a JSON lines file (default: stdin)")
    args = parser.parse_args(argv)
    if args.what == "run":
        print(run_audit())
    elif args.what == "auto":
        print(f"{auto()} checks added by rule")
    elif args.what == "pending":
        for row in pending():
            print(json.dumps(row))
    elif args.what == "match":
        edits, _ = collect()
        audit = json.loads((OUT / "audit.json").read_text())
        found, left = match(edits, audit, checks())
        for row in found:
            print(json.dumps(row))
        for edit_id in left:
            edit = edits[edit_id]
            print(f"to read: {edit_id} {edit['project']} {edit['path']}", file=sys.stderr)
    elif args.what == "show":
        print(show(args.edits))
    elif args.what == "record":
        lines = (args.input.read_text() if args.input else sys.stdin.read()).splitlines()
        rows = record(checks(), lines)
        write_checks(rows)
        print(f"{len(rows)} checks")
    elif args.what == "sheet":
        print(sheet(args.path))
    elif args.what == "kappa":
        print(json.dumps(kappa(args.path)))
    else:
        print(table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
