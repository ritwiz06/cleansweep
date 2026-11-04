"""Targeted tests for the diff audit's verdicts: a short test of the behavior a check says an edit
changes, run in the run's own environment on the project as the run found it, then again with the
edit applied. A test that passes before and fails after confirms the verdict (checked_by
"targeted test"); anything else leaves it to reading (LLM-judged).

    python scripts/experiments/v2/exp_audit_confirm.py run [--edits ID ...]
    python scripts/experiments/v2/exp_audit_confirm.py record

Tests: results/raw/diff_audit/tests/<edit>/test_<edit>.py, plus hide.txt for a removed dependency
(the packages a fresh install would no longer have, hidden as the Guard hides them), or
no_test.txt instead when no test could be written (why). A test runs on its edit and on every edit
whose check cites it as the same change (another seed or run). Each project is opened once, as the
run opened it (Docker for AIDev targets; the local copy for this repository and the fixtures),
and reset between edits. When an edit does not apply on its own, the run's earlier kept edits to
the same file are applied first and belong to "before". A light job: one workspace at a time,
waiting while the load is high.
run: results/raw/diff_audit/tests/results.json (per edit: applied, before and after outcomes,
confirmed).
record: diff_audit_checks.csv: a confirmed edit gets checked_by "targeted test" and the test's
docstring in its evidence; an edit with no_test.txt gets the reason in its evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from exp_diff_audit import (  # noqa: E402
    OUT,
    _wait_for_load,
    checks,
    kept_edits,
    tree_for,
    write_checks,
)

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402

TESTS = OUT / "tests"
RESULTS = TESTS / "results.json"
INJECTED_CLONES = "data/raw/aidev/injected"  # exp_inject.CLONES


def same_change(known: dict[str, dict]) -> dict[str, list[str]]:
    """edit -> the edits whose check cites it as the same change."""
    out: dict[str, list[str]] = {}
    for edit, check in sorted(known.items()):
        m = re.match(r"the same change as (\w{12})", check["evidence"])
        if m:
            out.setdefault(m.group(1), []).append(edit)
    return out


def earlier_edits(report: dict, item_id: str, path: str) -> list[str]:
    """The diffs of the run's kept edits to the same file before this one, in order."""
    out = []
    for edit in kept_edits(report):
        if edit["item_id"] == item_id:
            return out
        if edit["path"] == path:
            out.append(edit["diff"])
    return out


def opened(project: str, report: Path) -> tuple[str, dict]:
    """(workspace target, sandbox settings) as the run opened the project."""
    sandbox = dict(load_config()["core"].get("sandbox") or {})
    if project.startswith("aidev:"):
        if report.parent.parent.name == "inject":
            sandbox["aidev_clones"] = INJECTED_CLONES
        return project, sandbox
    tree = tree_for(project, report)
    if not tree.rev:
        return str(tree.repo), sandbox
    tmp = Path(tempfile.mkdtemp(prefix="cs_confirm_"))
    archive = subprocess.Popen(["git", "archive", tree.rev], cwd=tree.repo, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xf", "-", "-C", str(tmp)], stdin=archive.stdout, check=True)
    archive.wait()
    return str(tmp / tree.prefix.rstrip("/")) if tree.prefix else str(tmp), sandbox


def _applies(ws, diff: str) -> bool:
    proc = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=ws.path,
        input=diff if diff.endswith("\n") else diff + "\n",
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0


def _failures(ws) -> list[str]:
    """The failure lines (pytest's "E " lines) of the workspace's last test run."""
    out = getattr(ws, "last_test_output", "")
    return [line.strip() for line in out.splitlines() if line.startswith("E ")][:8]


def check_edit(ws, base: str, folder: Path, record: dict) -> dict:
    """Run one test before and after one edit in an open workspace, then reset it."""
    ws.rollback(base)
    prefix = []
    if not _applies(ws, record["diff"]):
        report = json.loads(Path(record["report"]).read_text())
        prefix = earlier_edits(report, record["item_id"], record["path"])
        if not all(ws.apply_patch(d) for d in prefix):
            ws.rollback(base)
            return {"applied": False, "prefix": len(prefix), "confirmed": False}
    dest = Path(ws.path) / "_cs_audit"
    # pytest's cache files are ignored by the workspace's git, so a rollback leaves them
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(folder, dest)
    before = ws.run_tests(["_cs_audit"])
    before_errors = _failures(ws)
    applied = ws.apply_patch(record["diff"])
    hide = folder / "hide.txt"
    hidden = ws.hide_packages(hide.read_text().split()) if applied and hide.exists() else None
    after = ws.run_tests(["_cs_audit"]) if applied else None
    after_errors = _failures(ws) if applied else []
    output = getattr(ws, "last_test_output", "")[-1500:]
    if hidden is not None:
        ws.restore_packages()
    shutil.rmtree(dest, ignore_errors=True)
    ws.rollback(base)
    return {
        "applied": applied,
        "prefix": len(prefix),
        "hidden": hidden,
        "before_ok": before.ok,
        "before_failed": before.failed_ids,
        "before_errors": before_errors,
        "after_ok": after.ok if after else None,
        "after_failed": after.failed_ids if after else [],
        "after_errors": after_errors,
        "confirmed": bool(applied and before.ok and after is not None and not after.ok),
        "output": output,
    }


def todo(only: list[str] | None = None) -> dict[str, list[tuple[str, dict]]]:
    """workspace target -> [(test folder's edit, audit record of an edit it covers)]."""
    audit = json.loads((OUT / "audit.json").read_text())
    copies = same_change(checks())
    out: dict[str, list[tuple[str, dict]]] = {}
    for folder in sorted(TESTS.glob("*/test_*.py")):
        edit = folder.parent.name
        if only and edit not in only:
            continue
        for covered in [edit, *copies.get(edit, [])]:
            if covered in audit:
                record = {**audit[covered], "edit": covered}
                key = f"{record['project']}|{Path(record['report']).parent.parent.name}"
                out.setdefault(key, []).append((edit, record))
    return out


def run(only: list[str] | None = None) -> Path:
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    for key, pairs in todo(only).items():
        _wait_for_load()
        project, report = pairs[0][1]["project"], Path(pairs[0][1]["report"])
        target, sandbox = opened(project, report)
        print(f"open {key} ({len(pairs)} edits)", flush=True)
        try:
            ws = open_workspace(target, sandbox)
        except Exception as exc:  # an install that fails is a result too
            error = str(exc)[:300]
            for test, record in pairs:
                results[record["edit"]] = {"test": test, "error": error, "confirmed": False}
            continue
        try:
            base = ws.checkpoint("confirm base")
            for test, record in pairs:
                out = check_edit(ws, base, TESTS / test, record)
                results[record["edit"]] = {"test": test, "target": target, **out}
                print(f"  {record['edit']} (test {test}) confirmed={out['confirmed']}", flush=True)
                RESULTS.write_text(json.dumps(results, indent=1))
        finally:
            ws.close()
    RESULTS.write_text(json.dumps(results, indent=1))
    return RESULTS


def _doc(test: Path) -> str:
    text = test.read_text()
    m = re.match(r'\s*"""(.*?)"""', text, re.S)
    return " ".join(m.group(1).split()) if m else ""


def recorded(check: dict, result: dict | None, folder: Path) -> dict:
    """The check with a confirmed targeted test or a no-test reason added to its evidence. A
    "targeted test" from before this script (run outside the run's environment) that is not
    confirmed here goes back to reading."""
    if result and result.get("confirmed"):
        doc = _doc(folder / f"test_{folder.name}.py")
        evidence = check["evidence"]
        if "Targeted test (passes before" not in evidence:
            evidence += f" Targeted test (passes before the edit, fails after): {doc}"
        return {**check, "evidence": evidence, "checked_by": "targeted test"}
    out = dict(check)
    if out["checked_by"] == "targeted test":
        out["checked_by"] = "reading (LLM-judged)"
        out["evidence"] += " The earlier test ran outside the run's environment."
    reason = folder / "no_test.txt"
    if reason.exists() and "No targeted test" not in out["evidence"]:
        out["evidence"] += " No targeted test: " + " ".join(reason.read_text().split())
    return out


def record() -> int:
    """Write the confirmed tests and the no-test reasons into diff_audit_checks.csv."""
    known = checks()
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    copies = same_change(known)
    folders = {p.name: p for p in TESTS.iterdir() if p.is_dir()} if TESTS.exists() else {}
    changed = 0
    for root, folder in folders.items():
        for edit in [root, *copies.get(root, [])]:
            if edit in known:
                new = recorded(known[edit], results.get(edit), folder)
                changed += new != known[edit]
                known[edit] = new
    write_checks(list(known.values()))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "record"])
    parser.add_argument("--edits", nargs="*", help="only these test folders")
    args = parser.parse_args(argv)
    if args.what == "run":
        print(run(args.edits))
    else:
        print(f"{record()} checks updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
