"""Engineer: applies one work package with the deterministic edits, then, once the package has
passed its checks, makes its one commit on the delivery branch."""

from __future__ import annotations

import os
import subprocess

from cleansweep.core.models import EditResult
from cleansweep.guard import apply_edit
from cleansweep.sandbox.workspace import GIT_ID

NAME = "engineer"


def _git(ws, *args: str, stdin: str | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run(
        ["git", *GIT_ID, *args],
        cwd=ws.path,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return proc.stdout.strip()


def apply(rt, pkg) -> None:
    """Apply a package's edits; edits that can't be applied are skipped, not forced."""
    pkg.start = rt.ws.checkpoint(f"before {pkg.package_id}")
    prev = pkg.start
    pkg.applied = []
    for iid in pkg.items:
        item = rt.items[iid]
        call = rt.log.emit(
            "tool_call",
            agent=NAME,
            payload={"tool": "apply_edit", "args": {"item": iid, "action": item.action}},
        )
        ok = apply_edit(rt.ws, item)
        if ok:
            rt.item_diffs[iid] = rt.ws.diff(prev)
            prev = rt.ws.checkpoint(f"edit {iid}")
            pkg.applied.append(iid)
        else:
            rt.results[iid] = EditResult(iid, "skipped", notes="edit could not be applied")
        rt.log.emit(
            "tool_result",
            agent=NAME,
            parent=call["id"],
            payload={"tool": "apply_edit", "item": iid, "applied": ok},
        )
    not_applied = [i for i in pkg.items if i not in pkg.applied]
    if not pkg.applied:
        pkg.status, pkg.stage = "skipped", "done"
    else:
        pkg.status, pkg.stage = "applied", "test"
        pkg.diff_id = rt.artifact("diff", rt.ws.diff(pkg.start))
    rt.checks += 1
    rt.board.post(
        "package_applied",
        NAME,
        {"package": pkg.package_id, "applied": pkg.applied, "not_applied": not_applied},
        artifacts=[pkg.diff_id] if pkg.diff_id else [],
    )
    items = [rt.items[i] for i in pkg.applied]
    rt.log.v1(
        "check_start",
        {
            "n": rt.checks,
            "items": pkg.applied,
            "units": [i.unit.key for i in items],
            "categories": [i.category for i in items],
        },
    )


def commit(rt, pkg) -> None:
    """Make the package's commit on the delivery branch: the workspace tree as it is now."""
    sha = rt.ws.checkpoint(f"{pkg.package_id} kept")
    tree = _git(rt.ws, "rev-parse", f"{sha}^{{tree}}")
    pkg.parent = rt.delivery_tip or rt.ws.base
    pkg.commit = _git(
        rt.ws, "commit-tree", tree, "-p", pkg.parent, "-F", "-", stdin=message(rt, pkg)
    )
    rt.delivery_tip = pkg.commit
    pkg.stage = "done"
    rt.log.emit(
        "tool_result",
        agent=NAME,
        payload={"tool": "commit", "package": pkg.package_id, "commit": pkg.commit},
    )


def message(rt, pkg) -> str:
    lines = [pkg.goal, "", f"CleanSweep work package {pkg.package_id} ({pkg.status}).", ""]
    for iid in pkg.applied:
        item = rt.items[iid]
        lines.append(f"- {item.action} {item.unit.key}: {item.reason}"[:300])
    return "\n".join(lines) + "\n"


def revert_last(rt) -> bool:
    """Undo the latest kept package in the workspace and rebuild the delivery branch without
    it. False when no kept package is left."""
    kept = [p for p in rt.packages if p.status in ("kept", "repaired") and p.commit]
    if not kept:
        return False
    pkg = kept[-1]
    patch = _git(rt.ws, "diff", "--binary", pkg.parent, pkg.commit)
    if patch:
        subprocess.run(
            ["git", *GIT_ID, "apply", "-R", "--whitespace=nowarn", "-"],
            cwd=rt.ws.path,
            input=patch + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
    rt.ws.checkpoint(f"revert {pkg.package_id}")
    pkg.status = "reverted"
    for iid in pkg.applied:
        rt.results[iid] = EditResult(
            iid,
            "rolled_back",
            diff=rt.item_diffs.get(iid, ""),
            notes="reverted in FINAL VERIFY: the full suite was worse than the baseline",
        )
    rebuild_chain(rt)
    rt.log.emit("decision", agent=NAME, payload={"revert": pkg.package_id})
    return True


def rebuild_chain(rt) -> None:
    """Recreate the delivery commits for the packages still kept, in order, on the base."""
    index = rt.out / "delivery.index"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_INDEX_FILE"] = str(index)

    def git(*args: str, stdin: str | None = None) -> str:
        return subprocess.run(
            ["git", *GIT_ID, *args],
            cwd=rt.ws.path,
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout.strip()

    git("read-tree", rt.ws.base)
    tip = rt.ws.base
    for pkg in rt.packages:
        if pkg.status not in ("kept", "repaired") or not pkg.commit:
            continue
        diff = git("diff", "--binary", pkg.parent, pkg.commit)
        if diff:
            git("apply", "--cached", "--binary", "-", stdin=diff + "\n")
        tree = git("write-tree")
        pkg.parent = tip
        pkg.commit = git("commit-tree", tree, "-p", tip, "-F", "-", stdin=message(rt, pkg))
        tip = pkg.commit
    index.unlink(missing_ok=True)
    rt.delivery_tip = tip if tip != rt.ws.base else None
