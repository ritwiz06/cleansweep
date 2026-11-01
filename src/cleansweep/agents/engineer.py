"""Engineer: applies one work package with the deterministic edits, then, once the package has
passed its checks, makes its one commit on the delivery branch. In thorough mode, a duplicate or
wrapper with no deterministic rewrite gets one from the LLM (its own file only)."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import jsonschema

from cleansweep.analysis.graph import module_name
from cleansweep.core.models import EditResult
from cleansweep.guard import apply_edit
from cleansweep.guard.difftest import defs, segment
from cleansweep.reviewer.rewrite import _unified
from cleansweep.sandbox.workspace import GIT_ID

from .llm import acting
from .protocol import REASONING_OFF, load_prompt

NAME = "engineer"
MAX_FILE_CHARS = 12000
REWRITE_SCHEMA = {
    "type": "object",
    "required": ["edits"],
    "properties": {
        "edits": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["old", "new"],
                "properties": {
                    "old": {"type": "string", "minLength": 1},
                    "new": {"type": "string"},
                },
            },
        }
    },
}


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


def _rewrite_task(rt, item, text: str) -> str | None:
    keep_path, _, keep_name = (item.keep_target or "").partition("::")
    if not keep_name:
        return None
    try:
        keep_text = (Path(rt.ws.path) / keep_path).read_text(encoding="utf-8")
    except OSError:
        return None
    node = defs(keep_text).get(keep_name)
    if node is None:
        return None
    return (
        f"File {item.unit.path}:\n```python\n{text}\n```\n"
        f"The kept copy, `{keep_name}` in {keep_path} (module {module_name(keep_path)}):\n"
        f"```python\n{segment(keep_text, node)}\n```\n"
        f"Remove the duplicate `{item.unit.name}` from {item.unit.path} and make its uses in this "
        f"file use the kept copy instead. Evidence: {'; '.join(item.evidence[:4])}"
    )


def llm_rewrite(rt, item, budget) -> str:
    """Thorough mode: a patch for a duplicate or wrapper with no deterministic rewrite, from one
    LLM request. Only the item's own file changes; uses in other files rule it out. "" when
    there is no usable rewrite."""
    path = item.unit.path
    if rt.llm is None or any(rt.graph.file_of(c) != path for c in rt.graph.callers(item.unit.key)):
        return ""
    text = (Path(rt.ws.path) / path).read_text(encoding="utf-8")
    task = _rewrite_task(rt, item, text) if len(text) <= MAX_FILE_CHARS else None
    if task is None:
        return ""
    messages = [
        {"role": "system", "content": load_prompt(NAME)},
        {"role": "user", "content": task},
    ]
    try:
        with acting(NAME, budget):
            reply = rt.llm.chat_json(messages, temperature=0.0, extra_body=REASONING_OFF)
        jsonschema.validate(reply, REWRITE_SCHEMA)
    except Exception:  # out of budget, LLM error or a malformed reply: no rewrite
        return ""
    new = text
    for edit in reply["edits"]:
        if new.count(edit["old"]) != 1:
            return ""
        new = new.replace(edit["old"], edit["new"], 1)
    try:
        ast.parse(new)
    except SyntaxError:
        return ""
    if new == text:
        return ""
    return _unified(path, text.splitlines(keepends=True), new.splitlines(keepends=True))


def apply(rt, pkg) -> None:
    """Apply a package's edits; edits that can't be applied are skipped, not forced."""
    pkg.start = rt.ws.checkpoint(f"before {pkg.package_id}")
    prev = pkg.start
    pkg.applied = []
    budget = rt.budget(NAME)
    for iid in pkg.items:
        item = rt.items[iid]
        if rt.mode == "thorough" and item.action == "replace_with" and not item.patch:
            item.patch = llm_rewrite(rt, item, budget)
            rt.log.emit(
                "tool_result",
                agent=NAME,
                payload={"tool": "llm_rewrite", "item": iid, "made": bool(item.patch)},
            )
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
    rt.record_usage(NAME, budget)
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
