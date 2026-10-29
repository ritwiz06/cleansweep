from __future__ import annotations

import ast
import json
import logging
import re
import shutil
from pathlib import Path

from cleansweep.analysis.graph import import_name, is_test_file, iter_py_files
from cleansweep.sandbox import open_workspace

log = logging.getLogger(__name__)

HIDDEN_DIR = "_hidden_checks"
START, END = ">>>>> Start Test Output", ">>>>> End Test Output"
ALT_PROMPT = (Path(__file__).parent / "prompts" / "hidden_tests.txt").read_text()
CODE_BLOCK = re.compile(r"```(?:python)?\n(.*?)```", re.DOTALL)
NOT_TESTED = {"setup.py", "conftest.py"}


def _hidden_source(target: str, cfg: dict) -> Path | None:
    explicit = cfg.get("exp", {}).get("hidden_tests") or cfg.get("hidden_tests")
    if explicit:
        return Path(explicit)
    sibling = Path(target.rstrip("/") + "_hidden")
    return sibling if sibling.is_dir() else None


def _loc(repo_dir: str) -> int:
    return sum(
        len((Path(repo_dir) / p).read_text(errors="replace").splitlines())
        for p in iter_py_files(repo_dir)
        if not is_test_file(p) and not p.startswith(HIDDEN_DIR)
    )


def _outcomes(result) -> dict:
    return {
        "passed": result.passed,
        "failed": result.failed,
        "errors": result.errors,
        "failed_ids": sorted(result.failed_ids),
    }


def _status(ws, test_paths: list[str] | None) -> dict[str, str]:
    """Test name -> status for one run, read with the instance's swebench log parser."""
    ws.run_tests(test_paths)
    out = getattr(ws, "last_test_output", "")
    section = out.split(START, 1)[-1].split(END, 1)[0]
    return ws.parser(section, ws.spec) or ws.parser(out, ws.spec)


def _hidden_status(ws, files: list[str]) -> dict[str, str]:
    """Run the hidden test files together; if that gives no results (one file can stop
    collection for all), run them one at a time."""
    if not files:
        return {}
    status = _status(ws, files)
    if status:
        return status
    merged: dict[str, str] = {}
    for f in files:
        merged.update(_status(ws, [f]))
    return merged


def run_swebench_hidden(target: str, final_diff: str, cfg: dict) -> dict:
    """Hidden checks for "swebench:<instance>:<agent>": the instance's FAIL_TO_PASS and
    PASS_TO_PASS tests plus PatchDiff's generated tests for this patch, in a fresh container,
    before and after the cleanup diff. The sweep's workspace never contains the PatchDiff tests.
    """
    from cleansweep.data import load_agent_patches
    from cleansweep.data.swebench import data_path

    _, instance_id, agent = target.split(":", 2)
    found = [p for p in load_agent_patches([agent]) if p.instance_id == instance_id]
    hidden = found[0].hidden_tests if found else []
    sandbox = {**cfg.get("core", {}).get("sandbox", {}), "flaky_runs": 0}
    ws = open_workspace(target, sandbox)
    try:
        folder = Path(ws.test_files[0]).parent if ws.test_files else Path(".")
        files = []
        for k, rel in enumerate(hidden):
            dest = folder / f"test_cs_hidden_{k}.py"
            (Path(ws.path) / dest).write_text(data_path(rel).read_text(encoding="utf-8"))
            files.append(dest.as_posix())
        named = set(ws.row["FAIL_TO_PASS"]) | set(ws.row["PASS_TO_PASS"])
        loc_before = _loc(ws.path)
        visible_before = _status(ws, None)
        # a PatchDiff test counts only if it gives the same result on every run before the diff
        runs = max(2, int(cfg.get("exp", {}).get("hidden_stability_runs", 3)))
        first, *others = [_hidden_status(ws, files) for _ in range(runs)]
        stable = {t: v for t, v in first.items() if all(o.get(t) == v for o in others)}
        final_diff = without_install_files(final_diff)
        if final_diff.strip() and not ws.apply_patch(final_diff):
            return {"available": True, "applied": False, "behavior_changed": None}
        visible_after = _status(ws, None)
        hidden_after = _hidden_status(ws, files)
        named_changed = sorted(t for t in named if visible_before.get(t) != visible_after.get(t))
        hidden_changed = sorted(t for t, v in stable.items() if hidden_after.get(t) != v)
        failing = ("FAILED", "ERROR")
        return {
            "available": True,
            "applied": True,
            "behavior_changed": bool(named_changed or hidden_changed),
            "f2p_p2p_changed": named_changed,
            "patchdiff_changed": hidden_changed,
            "patchdiff_files": len(files),
            "patchdiff_tests": len(stable),
            "patchdiff_unstable": len(first) - len(stable),
            "hidden_before": {"failed_ids": sorted(t for t, v in stable.items() if v in failing)},
            "hidden_after": {
                "failed_ids": sorted(t for t in stable if hidden_after.get(t) in failing)
            },
            "visible_new_failures": sorted(
                t
                for t, v in visible_after.items()
                if v in failing and visible_before.get(t) not in failing
            ),
            "loc_before": loc_before,
            "loc_after": _loc(ws.path),
        }
    finally:
        ws.close()


def _public_functions(repo_dir: str, graph, scope) -> dict[str, list]:
    """Public functions and public methods of public classes, per file, in the agent's non-test
    files (in every file when there is no agent scope)."""
    found: dict[str, list] = {}
    for u in graph.units():
        parts = (u.name or "_").split(".")
        if u.kind != "function" or len(parts) > 2 or any(p.startswith("_") for p in parts):
            continue
        if is_test_file(u.path) or Path(u.path).name in NOT_TESTED or HIDDEN_DIR in u.path:
            continue
        if scope is None or u.path in scope.files:
            found.setdefault(u.path, []).append(u)
    return found


def generate_alt_tests(repo_dir: str, graph, scope, llm, max_files: int, budget: int) -> dict:
    """One second-model test file per source file, for the files with the most public
    functions: {test file name: (source path, test code)}. A reply that isn't valid Python or
    has no test function is skipped."""
    found = _public_functions(repo_dir, graph, scope)
    out = {}
    for k, path in enumerate(sorted(found, key=lambda p: (-len(found[p]), p))[:max_files]):
        lines = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace").splitlines()
        code = "\n".join(lines)
        if len(code) > budget:  # only the public functions, as many as fit
            parts = ["\n".join(lines[u.start_line - 1 : u.end_line]) for u in found[path]]
            code = "\n\n".join(parts)[:budget]
        module = import_name(path)
        prompt = ALT_PROMPT.replace("{module}", module).replace("{path}", path)
        try:
            reply = llm.chat([{"role": "user", "content": prompt.replace("{code}", code)}])
        except Exception as exc:  # a failed request leaves this file untested
            log.warning("hidden test request failed for %s: %s", path, exc)
            continue
        m = CODE_BLOCK.search(reply)
        body = m.group(1) if m else reply
        try:
            tree = ast.parse(body)
        except SyntaxError:
            log.warning("hidden tests for %s are not valid Python; skipped", path)
            continue
        tests = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        if not any(n.name.lower().startswith("test") for n in tests):
            log.warning("no test functions in the reply for %s; skipped", path)
            continue
        out[f"test_cs_alt_{k}.py"] = (path, body)
    return out


def write_alt_tests(ws, target: str, cfg: dict, llm=None) -> list[str]:
    """Second-model tests for the target, written once into the cache (exp.hidden_alt_cache)
    and then copied into the workspace's _hidden_checks/ folder, which git ignores. Every
    method's hidden check on a target uses the same tests."""
    from cleansweep.analysis import build_graph
    from cleansweep.analysis.scope import agent_scope
    from cleansweep.llm import get_client

    exp = cfg.get("exp", {})
    name = re.sub(r"[^A-Za-z0-9_.@-]", "_", target)
    cache = Path(exp.get("hidden_alt_cache", ".cleansweep/hidden_tests")) / name
    if not cache.is_dir():
        llm = llm or get_client({**cfg.get("core", {}).get("llm", {}), "alt": True})
        graph = build_graph(ws.path)
        tests = generate_alt_tests(
            ws.path,
            graph,
            agent_scope(ws.path, graph),
            llm,
            int(exp.get("hidden_alt_max_files", 6)),
            int(exp.get("hidden_alt_budget_chars", 12000)),
        )
        cache.mkdir(parents=True)
        for file, (_, body) in tests.items():
            (cache / file).write_text(body, encoding="utf-8")
        sources = {file: path for file, (path, _) in tests.items()}
        meta = {"model": getattr(llm, "model", None), "sources": sources}
        (cache / "meta.json").write_text(json.dumps(meta, indent=1))
    dest = Path(ws.path) / HIDDEN_DIR
    dest.mkdir(exist_ok=True)
    files = sorted(cache.glob("test_cs_alt_*.py"))
    for f in files:
        shutil.copy(f, dest / f.name)
    return [f"{HIDDEN_DIR}/{f.name}" for f in files]


def without_install_files(diff: str) -> str:
    """The diff without files an install writes (*.egg-info), which a fresh workspace's own
    install writes again, so the diff would not apply there."""
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    return "".join(p for p in parts if ".egg-info/" not in p.split("\n", 1)[0])


def _statuses(ws, files: list[str]) -> dict[str, str]:
    ws.run_tests(files)
    return dict(ws.last_statuses)


def run_alt_hidden(target: str, final_diff: str, cfg: dict, llm=None) -> dict:
    """Hidden checks from a second model (EA-04): pytest tests that the ALT model writes for the
    public functions in the agent's files, run in a fresh workspace before and after the
    cleanup diff. A test counts only if it gives the same result on every one of
    exp.hidden_stability_runs runs before the diff. The tests are written only here, after the
    sweep, so the Guard never sees them."""
    ws = open_workspace(target, cfg.get("core", {}).get("sandbox"))
    try:
        files = write_alt_tests(ws, target, cfg, llm)
        if not files:
            return {"available": False, "reason": "no second-model tests"}
        runs = max(2, int(cfg.get("exp", {}).get("hidden_stability_runs", 3)))
        first, *others = [_statuses(ws, files) for _ in range(runs)]
        stable = {t: v for t, v in first.items() if all(o.get(t) == v for o in others)}
        final_diff = without_install_files(final_diff)
        if final_diff.strip() and not ws.apply_patch(final_diff):
            return {"available": True, "applied": False, "behavior_changed": None}
        after = _statuses(ws, files)
        changed = sorted(t for t, v in stable.items() if after.get(t) != v)
        failing = ("failed", "error")
        return {
            "available": True,
            "applied": True,
            "behavior_changed": bool(changed),
            "alt_changed": changed,
            "alt_files": len(files),
            "alt_tests": len(stable),
            "alt_unstable": len(first) - len(stable),
            "alt_passing": sum(v == "passed" for v in stable.values()),
            "hidden_before": {"failed_ids": sorted(t for t, v in stable.items() if v in failing)},
            "hidden_after": {"failed_ids": sorted(t for t in stable if after.get(t) in failing)},
        }
    finally:
        ws.close()


def run_hidden_checks(target: str, final_diff: str, cfg: dict) -> dict:
    """Run checks the Guard never saw, before and after the cleanup diff, and compare."""
    if target.startswith("swebench:"):
        return run_swebench_hidden(target, final_diff, cfg)
    if target.startswith("aidev:"):
        return run_alt_hidden(target, final_diff, cfg)
    src = _hidden_source(target, cfg)
    if src is None:
        return {"available": False}
    ws = open_workspace(target, cfg.get("core", {}).get("sandbox"))
    try:
        shutil.copytree(src, Path(ws.path) / HIDDEN_DIR)
        loc_before = _loc(ws.path)
        hidden_before = ws.run_tests([HIDDEN_DIR])
        visible_before = ws.run_tests(None)
        applied = ws.apply_patch(final_diff) if final_diff.strip() else True
        if not applied:
            return {"available": True, "applied": False, "behavior_changed": None}
        hidden_after = ws.run_tests([HIDDEN_DIR])
        visible_after = ws.run_tests(None)
        changed = (
            sorted(hidden_before.failed_ids) != sorted(hidden_after.failed_ids)
            or hidden_before.errors != hidden_after.errors
        )
        return {
            "available": True,
            "applied": True,
            "behavior_changed": changed,
            "hidden_before": _outcomes(hidden_before),
            "hidden_after": _outcomes(hidden_after),
            "visible_new_failures": sorted(
                set(visible_after.failed_ids) - set(visible_before.failed_ids)
            ),
            "loc_before": loc_before,
            "loc_after": _loc(ws.path),
        }
    finally:
        ws.close()
