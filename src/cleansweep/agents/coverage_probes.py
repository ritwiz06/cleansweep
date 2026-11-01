"""Coverage-guided differential probes (the Validator's probe rounds).

v1 asks the LLM once for probe cases. Here, after each round the probes run under coverage on
the version before the change, and the next round asks for cases that reach the changed lines
still uncovered. Target lines: the changed statements inside functions that still exist, and the
whole body of a removed duplicate or wrapper (its probes run against the replacement).

Functions in standalone scripts (no __init__.py beside them, or a file name that cannot be
imported) are probed too: the harness loads those files by path under an importable name, so
their main block does not run, and stubs the third-party modules they import that the
project's environment lacks (a PEP 723 script's own dependencies, say)."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import replace
from pathlib import Path

from cleansweep.guard.difftest import (
    Target,
    _setting,
    _valid_probe,
    changes_since,
    defs,
    get_probes,
    probe_mode,
    probe_versions,
    run_harness,
    select_targets,
    sys_paths,
)

from .protocol import REASONING_OFF, load_prompt

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")
NUMBERED_LINES = 80


def _old_changed_lines(ws, start: str) -> dict[str, set[int]]:
    """Line numbers, in the version at `start`, that the change removes or rewrites."""
    diff = subprocess.run(
        ["git", "diff", "-U0", start, "--", "*.py"], cwd=ws.path, capture_output=True, text=True
    ).stdout
    out: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = line[6:] if line.startswith("--- a/") else None
        m = HUNK.match(line)
        if m and path:
            first, count = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(path, set()).update(range(first, first + count))
    return out


def _statement_of(node: ast.AST, line: int) -> int | None:
    """First line of the innermost statement inside `node` that contains `line`."""
    best = None
    for n in ast.walk(node):
        if (
            isinstance(n, ast.stmt)
            and n is not node
            and n.lineno <= line <= (n.end_lineno or n.lineno)
        ):
            if best is None or n.lineno >= best.lineno:
                best = n
    return best.lineno if best is not None else None


def target_statements(ws, start: str, changes: dict, targets: list[Target]) -> dict[str, set[int]]:
    """{file: statement lines the probes should run}, in the version before the change."""
    changed = _old_changed_lines(ws, start)
    swaps = {t.key for t in targets if t.swap}
    wanted: dict[str, set[int]] = {}
    for path, (before, after) in changes.items():
        if before is None or path not in changed:
            continue
        old, new = defs(before), defs(after)
        for qual, node in old.items():
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            span = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            if f"{path}::{qual}" in swaps:
                body = {
                    n.lineno for n in ast.walk(node) if isinstance(n, ast.stmt) and n is not node
                }
                wanted.setdefault(path, set()).update(body)
            elif qual in new:
                for line in changed[path] & span:
                    stmt = _statement_of(node, line)
                    if stmt is not None:
                        wanted.setdefault(path, set()).add(stmt)
    return {p: s for p, s in wanted.items() if s}


def script_module(path: str) -> str:
    """An importable module name for a script path: benchmark/compute-time.py ->
    benchmark.compute_time."""
    parts = [re.sub(r"\W", "_", part) for part in path[:-3].split("/")]
    return ".".join(f"_{p}" if p[:1].isdigit() else p for p in parts)


def is_script(repo_dir: str, path: str) -> bool:
    """A .py file the harness has to load by path: no __init__.py beside it, or a name that
    cannot be imported."""
    root = Path(repo_dir)
    if not (root / path).is_file():
        return False
    folder = (root / path).parent
    named = all(part.isidentifier() for part in path[:-3].split("/"))
    return (
        not named
        or (folder != root and not (folder / "__init__.py").exists())
        or (folder == root and path != "setup.py")
    )


def script_targets(repo_dir: str, targets: list[Target]) -> tuple[list[Target], dict[str, str]]:
    """Targets in scripts get an importable module name (also in their swaps); returns the
    targets and {module: path} for the harness to load by path."""
    scripts: dict[str, str] = {}

    def name_for(module: str) -> str:
        path = module.replace(".", "/") + ".py"
        if not is_script(repo_dir, path):
            return module
        scripts[script_module(path)] = path
        return script_module(path)

    out = []
    for t in targets:
        path = t.key.split("::")[0]
        if not is_script(repo_dir, path):
            out.append(t)
            continue
        module = script_module(path)
        scripts[module] = path
        swap = t.swap and {
            **t.swap,
            "module": module,
            "source_module": name_for(t.swap["source_module"]),
        }
        out.append(replace(t, module=module, swap=swap))
    return out, scripts


def _spec(targets, checks, probes, paths) -> tuple[dict, dict]:
    use = [t for t in targets if t.key in probes]
    files = {f"t{i}.py": probes[t.key] for i, t in enumerate(use)}
    spec = {
        "paths": paths,
        "probes": [f"t{i}" for i in range(len(use))],
        "modules": [c.module for c in checks],
    }
    return spec, files


def _numbered(source: str, first_line: int) -> str:
    lines = source.splitlines()[:NUMBERED_LINES]
    return "\n".join(f"{first_line + i}: {line}" for i, line in enumerate(lines))


def ask_more(
    llm, targets: list[Target], probes: dict[str, str], missing: dict[str, set[int]], changes: dict
) -> dict[str, str]:
    """One request for more cases, for each target whose code holds uncovered lines."""
    blocks, wanted = [], []
    for t in targets:
        path = t.key.split("::")[0]
        node = defs(changes.get(path, (None, None))[0]).get(t.qualname)
        if node is None:
            continue
        span = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        lines = sorted(missing.get(path, set()) & span)
        if not lines:
            continue
        wanted.append(t)
        blocks.append(
            f"### Target id: {t.key}\nimport: {t.import_line}\nnot run yet: lines {lines}\n"
            f"```python\n{_numbered(t.source, node.lineno)}\n```\n"
            f"cases so far:\n```python\n{probes.get(t.key, '(none)')[:2000]}\n```"
        )
    if not blocks:
        return {}
    messages = [
        {"role": "system", "content": load_prompt("validator")},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]
    try:
        reply = llm.chat_json(messages, temperature=0.0, extra_body=REASONING_OFF)
    except Exception:  # budget or LLM failure: no new cases
        return {}
    entries = reply.get("probes", []) if isinstance(reply, dict) else []
    keys = {t.key for t in wanted}
    return {
        str(e.get("target")): e["code"]
        for e in entries
        if isinstance(e, dict)
        and str(e.get("target")) in keys
        and isinstance(e.get("code"), str)
        and _valid_probe(e["code"])
    }


def probe_with_coverage(
    ws,
    start: str,
    items,
    graph,
    llm,
    cfg: dict,
    rounds: int = 3,
    target: float = 0.9,
    guided: bool = True,
):
    """Probe the change since `start`, adding rounds until the changed lines are covered.

    Returns (DiffOutcome or None, info) where info has coverage (0-1 or None when not measured),
    rounds, targets and a note. The workspace ends where it started."""
    changes = changes_since(ws, start)
    targets, checks = select_targets(
        ws.path, changes, items, graph, int(_setting(cfg, "max_targets"))
    )
    if not targets and not checks:
        info = {"coverage": None, "rounds": 0, "targets": 0, "cases_by_target": {}}
        return None, {**info, "note": "nothing to probe"}
    targets, scripts = script_targets(ws.path, targets)
    mode = probe_mode(ws, cfg)
    probes, note = get_probes(targets, llm, cfg, mode)
    wanted = target_statements(ws, start, changes, targets)
    paths = sys_paths(ws.path)
    after_sha = ws.checkpoint("probe: after")
    all_targets, all_probes = list(targets), dict(probes)
    reached, used = None, 1

    def at(commit: str, coverage_files=None):
        def run(spec: dict, files: dict[str, str]) -> dict:
            ws.rollback(commit)
            if scripts:
                spec = {**spec, "scripts": scripts}
            return run_harness(ws, spec, files, cfg, mode, coverage_files=coverage_files)

        return run

    try:
        if guided and mode == "direct" and wanted:
            while True:
                spec, files = _spec(all_targets, checks, all_probes, paths)
                result = at(start, sorted(wanted))(spec, files) if files else {}
                ran = {p: set(lines) for p, lines in (result.get("coverage") or {}).items()}
                missing = {p: s - ran.get(p, set()) for p, s in wanted.items()}
                total = sum(len(s) for s in wanted.values())
                reached = (
                    round(1 - sum(len(s) for s in missing.values()) / total, 3) if total else None
                )
                if reached is None or reached >= target or used >= rounds or llm is None:
                    break
                extra = ask_more(llm, targets, all_probes, missing, changes)
                if not extra:
                    break
                for t in targets:
                    if t.key in extra:
                        clone = Target(
                            f"{t.key}#r{used + 1}", t.module, t.qualname, t.source, t.swap
                        )
                        all_targets.append(clone)
                        all_probes[clone.key] = extra[t.key]
                used += 1
        first: list[dict] = []

        def before(spec: dict, files: dict[str, str]) -> dict:
            out = at(start)(spec, files)
            first.append(out)
            return out

        outcome = probe_versions(before, at(after_sha), all_targets, checks, all_probes, paths, cfg)
    finally:
        ws.rollback(after_sha)
    probed = sum(t.key in all_probes for t in targets)
    # cases each target's probes ran on the before version (follow-up rounds count for their
    # target): a rewrite is verified only by cases against its own target, not by module checks
    cases: dict[str, int] = {}
    with_probes = [t for t in all_targets if t.key in all_probes]
    for i, t in enumerate(with_probes):
        result = (first[0].get("probes", {}) if first else {}).get(f"t{i}") or {}
        key = t.key.split("#r")[0]
        cases[key] = cases.get(key, 0) + (len(result.get("cases", {})) if result.get("ok") else 0)
    loaded = (first[0].get("scripts") or {}) if first else {}
    stubbed = sorted({m for r in loaded.values() for m in r.get("stubbed", [])})
    if scripts:
        ok = sum(bool(r.get("ok")) for r in loaded.values())
        note = (
            (note + "; " if note else "")
            + f"{ok}/{len(scripts)} scripts loaded by path"
            + (f" (stubbed: {', '.join(stubbed)})" if stubbed else "")
        )
    info = {
        "coverage": reached,
        "scripts": loaded,
        "rounds": used,
        "targets": len(targets),
        "target_lines": sum(len(s) for s in wanted.values()),
        "cases_by_target": cases,
        "note": f"{probed}/{len(targets)} targets probed, {len(checks)} module checks ({mode} mode)"
        + (f"; {note}" if note else ""),
    }
    return outcome, info
