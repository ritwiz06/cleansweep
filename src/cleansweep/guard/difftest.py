"""Differential probes: LLM-written calls run on the code before and after an edit.

The LLM only writes inputs. Our harness (probe_harness.py) runs them and records results, so a
probe never decides what is correct; it only shows whether the two versions agree.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from cleansweep.analysis.graph import is_test_file
from cleansweep.core.models import CleanupItem, DiffOutcome

log = logging.getLogger(__name__)

PROMPT_VERSION = "probe-v1"
PROMPT = (Path(__file__).parent / "prompts" / "probe.txt").read_text()
HARNESS = Path(__file__).parent / "probe_harness.py"
PROBE_DIR = "_probes"  # git-excluded inside workspaces
SOURCE_LINES = 60
DEFAULTS = {
    "max_targets": 10,
    "probe_timeout_s": 300,
    "probe_case_timeout_s": 10,
    "probe_max_cases": 8,
    "probe_cache_dir": ".cleansweep/probes",
}


@dataclass
class Target:
    key: str  # "path::Qual.name"
    module: str  # dotted import name
    qualname: str
    source: str  # the target's code in the before version
    swap: dict | None = None  # replacement probe: after the edit, run with this name re-bound

    @property
    def import_line(self) -> str:
        return f"from {self.module} import {self.qualname.split('.')[0]}"

    @property
    def cache_key(self) -> str:
        text = f"{PROMPT_VERSION}\n{self.key}\n{self.source}"
        return hashlib.sha256(text.encode()).hexdigest()[:20]


@dataclass
class ModuleCheck:
    module: str
    allowed_lost: set[str]  # public names the edit removes on purpose


def _setting(cfg: dict, key: str):
    return (cfg or {}).get(key, DEFAULTS[key])


def import_name(path: str) -> str | None:
    """Dotted module name for a repo path (src layout aware), or None if not a .py file."""
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or None


def _in_package(repo_dir: str, path: str) -> bool:
    folder = (Path(repo_dir) / path).parent
    return folder != Path(repo_dir) and (folder / "__init__.py").exists()


def defs(text: str | None) -> dict[str, ast.AST]:
    """Qualified name -> node for module-level functions and classes and class members."""
    if text is None:
        return {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    found: dict[str, ast.AST] = {}

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = prefix + node.name
                found.setdefault(name, node)
                if isinstance(node, ast.ClassDef):
                    walk(node.body, name + ".")

    walk(tree.body, "")
    return found


def segment(text: str, node: ast.AST) -> str:
    lines = text.splitlines()
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
    return "\n".join(lines[start - 1 : node.end_lineno])


def _import_names(text: str | None) -> set[str]:
    """Names bound by module-level imports."""
    try:
        tree = ast.parse(text or "")
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def _changed(old: ast.AST, new: ast.AST) -> bool:
    """True if a definition's code changed; formatting-only changes don't count."""
    return ast.dump(old) != ast.dump(new)


def _is_function(node: ast.AST | None) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)


def _swap_for(item: CleanupItem, module: str) -> dict | None:
    """For a duplicate or wrapper that was removed: bind its name to the code that replaces it."""
    name = item.unit.name or ""
    if item.action != "replace_with" or not name or "." in name:
        return None
    if item.keep_target and "::" in item.keep_target:
        path, keep = item.keep_target.split("::", 1)
        if "." in keep or not import_name(path):
            return None
        return {
            "module": module,
            "name": name,
            "source_module": import_name(path),
            "source_expr": keep,
        }
    for line in item.evidence:  # wrappers: "body is only `return pricing.total(...)` ..."
        if line.startswith("body is only `return ") and "(" in line:
            expr = line.split("`return ", 1)[1].split("(", 1)[0]
            return {"module": module, "name": name, "source_module": module, "source_expr": expr}
    return None


def select_targets(
    repo_dir: str,
    changes: dict[str, tuple[str | None, str | None]],
    items: list[CleanupItem],
    graph,
    max_targets: int,
) -> tuple[list[Target], list[ModuleCheck]]:
    """What to probe for a change: removed duplicates/wrappers against their replacement,
    changed functions, and callers of changed or deleted code; plus one import check per
    changed package module."""
    swaps: list[Target] = []
    changed: list[Target] = []
    callers: list[str] = []
    checks: list[ModuleCheck] = []
    before_defs = {p: defs(b) for p, (b, _) in changes.items()}
    after_defs = {p: defs(a) for p, (_, a) in changes.items()}
    by_unit = {i.unit.key: i for i in items}

    for path, (before, after) in sorted(changes.items()):
        module = import_name(path)
        if module is None or is_test_file(path) or before is None:
            continue
        old, new = before_defs[path], after_defs[path]
        deleted = [q for q in old if q not in new]
        modified = [q for q in old if q in new and _changed(old[q], new[q])]
        for q in deleted:
            item = by_unit.get(f"{path}::{q}")
            swap = _swap_for(item, module) if item else None
            if swap and _is_function(old[q]):
                swaps.append(Target(f"{path}::{q}", module, q, segment(before, old[q]), swap))
            callers += graph.callers(f"{path}::{q}") if graph is not None else []
        for q in modified:
            if _is_function(old[q]):
                changed.append(Target(f"{path}::{q}", module, q, segment(before, old[q])))
            callers += graph.callers(f"{path}::{q}") if graph is not None else []
        if after is not None and _in_package(repo_dir, path):
            lost_imports = _import_names(before) - _import_names(after)
            if path.endswith("__init__.py"):
                lost_imports = set()  # package re-exports are public API
            allowed = {q for q in deleted if "." not in q} | lost_imports
            checks.append(ModuleCheck(module, allowed))

    seen = {t.key for t in swaps + changed}
    caller_targets: list[Target] = []
    for key in sorted(set(callers)):
        path, _, q = key.partition("::")
        if key in seen or not q or is_test_file(path):
            continue
        module = import_name(path)
        # unchanged files read the same before and after
        text = changes[path][0] if path in changes else _read(repo_dir, path)
        node = defs(text).get(q)
        if module is None or text is None or not _is_function(node):
            continue
        if path in changes and q not in after_defs.get(path, {}):
            continue  # the caller itself is gone
        caller_targets.append(Target(key, module, q, segment(text, node)))
        seen.add(key)
    return (swaps + changed + caller_targets)[:max_targets], checks


def _read(repo_dir: str, path: str) -> str | None:
    try:
        return (Path(repo_dir) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _prompt(targets: list[Target]) -> str:
    blocks = []
    for t in targets:
        lines = t.source.splitlines()
        code = "\n".join(lines[:SOURCE_LINES]) + (
            "\n# ... (cut)" if len(lines) > SOURCE_LINES else ""
        )
        kind = (
            f"method of class {t.qualname.rsplit('.', 1)[0]}" if "." in t.qualname else "function"
        )
        blocks.append(
            f"### Target id: {t.key}\nimport: {t.import_line}\nkind: {kind}\n```python\n{code}\n```"
        )
    return PROMPT.format(targets="\n\n".join(blocks))


def _valid_probe(code: str) -> bool:
    if "def make_cases" not in code:
        return False
    try:
        compile(code, "<probe>", "exec")
    except SyntaxError:
        return False
    return True


def get_probes(targets: list[Target], llm, cfg: dict) -> tuple[dict[str, str], str]:
    """Probe code per target key: from the cache, else from one LLM request for all the rest."""
    cache = Path(_setting(cfg, "probe_cache_dir"))
    probes: dict[str, str] = {}
    missing = []
    for t in targets:
        path = cache / f"{t.cache_key}.py"
        if path.exists():
            probes[t.key] = path.read_text(encoding="utf-8")
        else:
            missing.append(t)
    if not missing:
        return probes, ""
    if llm is None:
        return probes, "no LLM for new probes"
    try:
        messages = [{"role": "user", "content": _prompt(missing)}]
        extra = (cfg or {}).get("probe_extra_body")
        if extra:
            reply = llm.chat_json(messages, temperature=0.0, extra_body=extra)
        else:
            reply = llm.chat_json(messages, temperature=0.0)
    except Exception as exc:  # a failed request leaves these targets unprobed
        log.warning("probe request failed: %s: %s", type(exc).__name__, exc)
        return probes, f"probe request failed: {type(exc).__name__}"
    entries = reply.get("probes", []) if isinstance(reply, dict) else reply
    by_key = {t.key: t for t in missing}
    cache.mkdir(parents=True, exist_ok=True)
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        target, code = by_key.get(str(entry.get("target"))), entry.get("code")
        if target is None or not isinstance(code, str) or not _valid_probe(code):
            continue
        (cache / f"{target.cache_key}.py").write_text(code, encoding="utf-8")
        probes[target.key] = code
    return probes, ""


def run_harness(ws, spec: dict, files: dict[str, str], cfg: dict) -> dict:
    """Write probe files and a spec under _probes/ in the workspace, run the harness, read JSON."""
    run_dir = Path(PROBE_DIR) / uuid.uuid4().hex[:12]
    folder = Path(ws.path) / run_dir
    folder.mkdir(parents=True)
    try:
        shutil.copy(HARNESS, folder / "harness.py")
        for name, code in files.items():
            (folder / name).write_text(code, encoding="utf-8")
        spec = {
            **spec,
            "out": str(run_dir / "out.json"),
            "probes": [{"id": pid, "file": str(run_dir / f"{pid}.py")} for pid in spec["probes"]],
            "max_cases": _setting(cfg, "probe_max_cases"),
            "case_timeout": _setting(cfg, "probe_case_timeout_s"),
        }
        (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        if hasattr(ws, "sync"):
            ws.sync()
        python = getattr(ws, "python", sys.executable)
        code, out = ws.run(
            [python, str(run_dir / "harness.py"), str(run_dir / "spec.json")],
            timeout=int(_setting(cfg, "probe_timeout_s")),
        )
        if hasattr(ws, "fetch"):
            ws.fetch(str(run_dir / "out.json"))
        result_path = folder / "out.json"
        if not result_path.exists():
            return {"error": f"harness exit {code}: {out[-500:]}"}
        return json.loads(result_path.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _short(text: str, n: int = 100) -> str:
    return text if len(text) <= n else text[:n] + "..."


IMPORT_NAME = re.compile(r"cannot import name '(\w+)'")


def compare(
    targets: list[Target],
    checks: list[ModuleCheck],
    before: tuple[dict, dict],
    after: dict,
) -> DiffOutcome:
    """Turn harness outputs into a DiffOutcome. Cases that differ between the two before-runs
    are unstable and dropped; so are probes that only fail after the edit because they import
    a name the edit removes on purpose (the module check covers those names)."""
    b1, b2 = before
    removed = set().union(*(c.allowed_lost for c in checks)) if checks else set()
    n_cases = n_unstable = 0
    mismatches: list[str] = []
    for i, t in enumerate(targets):
        pid = f"t{i}"
        r1, r2 = b1.get("probes", {}).get(pid), b2.get("probes", {}).get(pid)
        if not (r1 and r2 and r1.get("ok") and r2.get("ok")):
            continue  # the probe doesn't work on the before version: discard it
        stable = {k: v for k, v in r1["cases"].items() if r2["cases"].get(k) == v}
        n_unstable += len(r1["cases"]) - len(stable)
        if not stable:
            continue
        ra = after.get("probes", {}).get(pid)
        name = t.key + (f" vs {t.swap['source_module']}.{t.swap['source_expr']}" if t.swap else "")
        if not ra or not ra.get("ok"):
            error = (ra or {}).get("error") or after.get("error") or "no result"
            m = IMPORT_NAME.search(error)
            if m and m.group(1) in removed:
                continue
            n_cases += len(stable)
            mismatches.append(f"{name}: probe fails after the edit ({_short(error)})")
            continue
        n_cases += len(stable)
        for label, value in stable.items():
            got = ra["cases"].get(label, "missing")
            if got != value:
                mismatches.append(f"{name} [{label}]: before {_short(value)}, after {_short(got)}")
    for check in checks:
        m1 = b1.get("modules", {}).get(check.module)
        if not m1 or not m1.get("ok"):
            continue
        n_cases += 1
        ma = after.get("modules", {}).get(check.module)
        if not ma or not ma.get("ok"):
            error = (ma or {}).get("error") or after.get("error") or "no result"
            mismatches.append(f"module {check.module} no longer imports ({_short(error)})")
            continue
        # module-valued names come and go with import order; the modules stay importable
        lost = set(m1["names"]) - set(ma["names"]) - check.allowed_lost - set(m1.get("modules", []))
        if lost:
            mismatches.append(f"module {check.module} lost public names: {', '.join(sorted(lost))}")
    return DiffOutcome(not mismatches, n_cases, n_unstable, mismatches)


def probe_versions(
    run_before,
    run_after,
    targets: list[Target],
    checks: list[ModuleCheck],
    probes: dict[str, str],
    paths: list[str],
    cfg: dict,
) -> DiffOutcome | None:
    """Run the probes twice on the before version and once on the after version, then compare.

    run_before / run_after take (spec, files) and return the harness output for that version.
    In the after-run, each removed duplicate or wrapper name is bound to the code that
    replaces it (after the module check has listed the names), so its probe tests the
    replacement and other probes that import it still load.
    """
    targets = [t for t in targets if t.key in probes]
    if not targets and not checks:
        return None
    files = {f"t{i}.py": probes[t.key] for i, t in enumerate(targets)}
    spec = {
        "paths": paths,
        "probes": [f"t{i}" for i in range(len(targets))],
        "modules": [c.module for c in checks],
    }
    b1 = run_before(spec, files)
    b2 = run_before(spec, files)
    after = run_after({**spec, "swaps": [t.swap for t in targets if t.swap]}, files)
    return compare(targets, checks, (b1, b2), after)


def _git(repo_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True)


def changes_since(ws, start: str) -> dict[str, tuple[str | None, str | None]]:
    """Changed .py files since a checkpoint: path -> (text before, text now); None = absent."""
    _git(ws.path, "add", "-A")
    status = _git(ws.path, "diff", "--cached", "--name-only", start).stdout
    _git(ws.path, "reset", "-q")
    changes = {}
    for path in status.splitlines():
        if not path.endswith(".py") or path.startswith(PROBE_DIR + "/"):
            continue
        shown = _git(ws.path, "show", f"{start}:{path}")
        before = shown.stdout if shown.returncode == 0 else None
        changes[path] = (before, _read(ws.path, path))
    return changes


def sys_paths(repo_dir: str) -> list[str]:
    return [".", "src"] if (Path(repo_dir) / "src").is_dir() else ["."]


def probe_change(ws, start: str, items: list[CleanupItem], graph, llm, cfg: dict):
    """Probe the change from checkpoint `start` to the workspace's current state.

    Returns (DiffOutcome or None when there was nothing to probe, a short note). The workspace
    ends at the same state it started in.
    """
    changes = changes_since(ws, start)
    targets, checks = select_targets(
        ws.path, changes, items, graph, int(_setting(cfg, "max_targets"))
    )
    if not targets and not checks:
        return None, "nothing to probe"
    log.info(
        "probing %d functions (%s) and %d modules",
        len(targets),
        ", ".join(t.key + (" (vs its kept copy)" if t.swap else "") for t in targets),
        len(checks),
    )
    probes, note = get_probes(targets, llm, cfg)
    after_sha = ws.checkpoint("probe: after")

    def at(commit: str):
        def run(spec: dict, files: dict[str, str]) -> dict:
            ws.rollback(commit)
            return run_harness(ws, spec, files, cfg)

        return run

    try:
        outcome = probe_versions(
            at(start), at(after_sha), targets, checks, probes, sys_paths(ws.path), cfg
        )
    finally:
        ws.rollback(after_sha)
    n_probed = sum(t.key in probes for t in targets)
    note = f"{n_probed}/{len(targets)} targets probed, {len(checks)} module checks" + (
        f"; {note}" if note else ""
    )
    return outcome, note
