from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.analysis.scope import agent_scope
from cleansweep.core.models import CleanupItem, CleanupPlan, CodeUnit, EditResult, SweepReport
from cleansweep.guard import apply_edit
from cleansweep.llm import get_client
from cleansweep.sandbox import open_workspace

VULTURE_LINE = re.compile(r"^(.+?):(\d+): unused (function|method|class) '([^']+)'")
FENCE = re.compile(r"```(?:diff|patch)?\n(.*?)```", re.S)
PROMPT = (Path(__file__).parent / "prompts" / "one_shot.txt").read_text()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _report(
    ws,
    method: str,
    seed: int,
    started: str,
    t0: float,
    items: list[CleanupItem],
    results: list[EditResult],
    usage: dict | None = None,
) -> SweepReport:
    stats = {
        "items_total": len(items),
        "items_safe": len(items),
        "items_kept": sum(r.status == "kept" for r in results),
        "items_repaired": 0,
        "items_rolled_back": 0,
        "test_runs": ws.test_runs,
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    stats.update(usage or {})
    diff_stats = ws.diff_stats(ws.base)
    stats.update(
        lines_removed=diff_stats["lines_removed"],
        files_removed=diff_stats["files_removed"],
        wall_seconds=round(time.time() - t0, 2),
        final_diff=ws.diff(ws.base),
    )
    plan = CleanupPlan(ws.repo_id, started, items)
    return SweepReport(ws.repo_id, method, "now", seed, started, _now(), plan, results, stats)


def _host(cmd: list[str], cwd: str) -> str:
    # the tools run on the host copy; a Docker workspace's container doesn't have them
    proc = subprocess.run([sys.executable, "-m", *cmd], cwd=cwd, capture_output=True, text=True)
    return proc.stdout + proc.stderr


def tools_only(target: str, cfg: dict) -> SweepReport:
    """Baseline: delete whatever vulture flags and apply ruff fixes, with no checks.

    On SWE-bench targets it touches only the agent's code, like CleanSweep's agent scope: new
    functions vulture flags, unused imports in the agent's files, and formatting of the files
    the agent created."""
    started, t0 = _now(), time.time()
    ws = open_workspace(target, cfg.get("core", {}).get("sandbox"))
    try:
        scope = agent_scope(ws.path) if target.startswith("swebench:") else None
        out = _host(["vulture", ".", "--min-confidence", "60"], ws.path)
        items, results = [], []
        for line in out.splitlines():
            m = VULTURE_LINE.match(line.strip())
            if not m or is_test_file(m.group(1).removeprefix("./")):
                continue
            path, lineno, kind, name = m.groups()
            if scope is not None and not scope.covers_line(path.removeprefix("./"), int(lineno)):
                continue
            unit = CodeUnit(path.removeprefix("./"), "function", name, int(lineno))
            item = CleanupItem(
                f"vulture-{len(items)}",
                unit,
                "dead_code",
                "delete_unit",
                "safe",
                f"vulture flagged unused {kind} {name}",
                [line.strip()],
                ["vulture"],
            )
            items.append(item)
        for item in items:
            # vulture reports the bare name; find the qualified one at that line
            item.unit.name = _qualname_at(
                ws.path, item.unit.path, item.unit.start_line, item.unit.name
            )
            before = ws.checkpoint(f"tools {item.item_id}")
            status = "kept" if apply_edit(ws, item) else "skipped"
            results.append(EditResult(item.item_id, status, diff=ws.diff(before)))
        before = ws.checkpoint("tools ruff")
        fix_paths = sorted(f for f in scope.files if f.endswith(".py")) if scope else ["."]
        fmt_paths = sorted(f for f in scope.files_added if f.endswith(".py")) if scope else ["."]
        if fix_paths:
            _host(["ruff", "check", "--isolated", "--select", "F401", "--fix", *fix_paths], ws.path)
        if fmt_paths:
            _host(["ruff", "format", "--isolated", *fmt_paths], ws.path)
        ruff_item = CleanupItem(
            "ruff-fixes",
            CodeUnit(".", "file"),
            "unused_import",
            "apply_patch",
            "safe",
            "ruff F401 --fix and ruff format",
            [],
            ["ruff"],
        )
        items.append(ruff_item)
        results.append(EditResult(ruff_item.item_id, "kept", diff=ws.diff(before)))
        report = _report(ws, "tools_only", 0, started, t0, items, results)
        return report
    finally:
        ws.close()  # also on errors: a SWE-bench workspace holds a container


def _qualname_at(repo_dir: str, path: str, line: int, name: str) -> str:
    import ast

    try:
        tree = ast.parse((Path(repo_dir) / path).read_text())
    except (OSError, SyntaxError):
        return name
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if getattr(sub, "lineno", None) == line and getattr(sub, "name", "") == name:
                    return f"{node.name}.{name}"
    return name


def _collect_code(repo_dir: str, budget: int = 60000, paths: list[str] | None = None) -> str:
    parts, used = [], 0
    for path in paths if paths is not None else iter_py_files(repo_dir):
        text = (Path(repo_dir) / path).read_text(errors="replace")
        block = f"### {path}\n{text}\n"
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def _agent_files(repo_dir: str) -> list[str] | None:
    """Text files the agent patch created or changed (None without an agent patch commit)."""
    scope = agent_scope(repo_dir)
    if scope is None:
        return None
    out = []
    for path in sorted(scope.files):
        try:
            (Path(repo_dir) / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # deleted or binary
        out.append(path)
    return out


def one_shot_llm(target: str, cfg: dict, seed: int = 0) -> SweepReport:
    """Baseline: ask the model once for a cleanup diff and apply it with no checks.

    On SWE-bench targets the model sees only the files the agent patch created or changed."""
    started, t0 = _now(), time.time()
    ws = open_workspace(target, cfg.get("core", {}).get("sandbox"))
    try:
        llm = cfg.get("llm_client") or get_client(cfg.get("core", {}).get("llm"))
        paths = _agent_files(ws.path) if target.startswith("swebench:") else None
        prompt = PROMPT.replace("{code}", _collect_code(ws.path, paths=paths))
        messages = [{"role": "user", "content": prompt}]
        extra = cfg.get("exp", {}).get("one_shot_extra_body")
        if extra:
            reply = llm.chat(messages, temperature=0.0, seed=seed, extra_body=extra)
        else:
            reply = llm.chat(messages, temperature=0.0, seed=seed)
        m = FENCE.search(reply)
        patch = m.group(1) if m else reply
        item = CleanupItem(
            "one-shot",
            CodeUnit(".", "file"),
            "other",
            "apply_patch",
            "safe",
            "one-shot cleanup diff from the model",
            [],
            ["llm"],
            patch=patch,
        )
        applied = ws.apply_patch(patch)
        result = EditResult(
            item.item_id,
            "kept" if applied else "skipped",
            diff=ws.diff(ws.base),
            notes="" if applied else "diff did not apply",
        )
        report = _report(ws, "one_shot_llm", seed, started, t0, [item], [result], llm.usage())
        return report
    finally:
        ws.close()  # also on errors: a SWE-bench workspace holds a container
