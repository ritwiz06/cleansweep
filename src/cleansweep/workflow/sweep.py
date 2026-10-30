from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.analysis import build_graph, extract_features
from cleansweep.core.io import save_json, to_dict
from cleansweep.core.models import EditResult, SweepReport
from cleansweep.guard import Guard
from cleansweep.llm import get_client
from cleansweep.ranking import load_ranker
from cleansweep.reviewer import build_plan, propose_fix
from cleansweep.reviewer.planner import scope_report
from cleansweep.sandbox import open_workspace
from cleansweep.scheduler import apply_with_bisection, make_batches


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def make_llm(core_cfg: dict):
    """The Voyager client when enabled (auto = only if a key is set), else None."""
    llm_cfg = core_cfg.get("llm", {})
    enabled = llm_cfg.get("enabled", "auto")
    if enabled == "auto":
        enabled = bool(os.environ.get(llm_cfg.get("api_key_env", "VOYAGER_API_KEY")))
    return get_client(llm_cfg) if enabled else None


def report_path(out_dir: str, run_id: str, report: SweepReport) -> Path:
    safe_id = report.repo_id.replace("/", "_").replace(":", "_")
    return Path(out_dir) / run_id / f"{safe_id}__{report.method}__s{report.seed}.json"


def report_checks(guard, ws, on_event: Callable[[str, dict], None]) -> Callable[[list], bool]:
    """guard.check_batch that also reports each check, bisection halves included, to on_event:
    "check_start" with the batch, then "check" with its outcome and the run's totals so far."""
    count = 0

    def check(batch) -> bool:
        nonlocal count
        count += 1
        on_event(
            "check_start",
            {
                "n": count,
                "items": [i.item_id for i in batch],
                "units": [i.unit.key for i in batch],
                "categories": [i.category for i in batch],
            },
        )
        start = time.time()
        ok = guard.check_batch(batch)
        latest = {r.item_id: r for r in guard.results()}
        found = [latest.get(i.item_id) for i in batch]
        statuses = {
            i.item_id: (r.status if r else "unknown") for i, r in zip(batch, found, strict=True)
        }
        tests = next((r.tests for r in found if r is not None and r.tests is not None), None)
        ast_equal = next(
            (r.ast_equal for r in found if r is not None and r.ast_equal is not None), None
        )
        probes = next((r.diff_check for r in found if r is not None and r.diff_check), None)
        if ok and set(statuses.values()) == {"skipped"}:
            result = "skipped"
        elif ok:
            result = "repaired" if "repaired" in statuses.values() else "kept"
        else:
            result = "split in half" if len(batch) > 1 else "rolled back"
        on_event(
            "check",
            {
                "n": count,
                "ok": ok,
                "result": result,
                "statuses": statuses,
                "tests": to_dict(tests) if tests is not None else None,
                "ast_equal": ast_equal,
                "probes": to_dict(probes) if probes is not None else None,
                "test_runs": ws.test_runs,
                "lines_removed": ws.diff_stats(ws.base)["lines_removed"],
                "seconds": round(time.time() - start, 1),
            },
        )
        return ok

    return check


def run_sweep(
    target: str,
    cfg: dict,
    method: str = "cleansweep",
    seed: int = 0,
    on_event: Callable[[str, dict], None] | None = None,
) -> SweepReport:
    """Open, analyze, plan, rank, batch and guard one target; return the sweep report.

    on_event(name, payload), if given, is called after each step (open, analyze, plan, rank,
    batch, guard, report; each payload has the step's seconds), after the Guard's baseline test
    runs ("baseline") and around each Guard check (report_checks). A baseline method only reports
    "report"."""

    def emit(name: str, since: float | None = None, **payload) -> None:
        if on_event is not None:
            if since is not None:
                payload["seconds"] = round(time.time() - since, 1)
            on_event(name, payload)

    if method in ("tools_only", "one_shot_llm", "one_shot_retry"):
        from cleansweep import eval as baselines

        if method == "tools_only":
            report = baselines.tools_only(target, cfg)
        elif method == "one_shot_retry":
            report = baselines.one_shot_retry(target, cfg, seed)
        else:
            report = baselines.one_shot_llm(target, cfg, seed)
        emit("report", stats={k: v for k, v in report.stats.items() if k != "final_diff"})
        return report

    started, t0 = _now(), time.time()
    core = cfg.get("core", {})
    exp = cfg.get("exp", {})
    since = time.time()
    ws = open_workspace(target, core.get("sandbox"))
    try:
        llm = cfg.get("llm_client") or make_llm(core)
        model = getattr(llm, "model", None)
        emit("open", since, repo_id=ws.repo_id, workspace=ws.path, llm=model)

        since = time.time()
        graph = build_graph(ws.path)
        features = extract_features(ws.path, graph)
        emit("analyze", since, units=len(graph.units()))

        since = time.time()
        plan = build_plan(ws, graph, llm, use_llm=llm is not None, cfg=cfg)
        if on_event is not None:
            emit("plan", since, items=to_dict(plan.items))

        since = time.time()
        if method != "no_ranker":
            load_ranker(exp.get("ranker_path")).score(plan.items, features)
            emit("rank", since, scores={i.item_id: i.safe_score for i in plan.items})
        else:
            emit("rank", since, skipped=True)

        since = time.time()
        safe = [i for i in plan.items if i.lane == "safe" and i.action != "report_only"]
        max_size = 1 if method == "no_batching" else exp.get("batch_max_size", 8)
        batches = make_batches(safe, max_size)
        emit("batch", since, max_size=max_size, batches=[[i.item_id for i in b] for b in batches])

        since = time.time()
        guard_cfg = dict(core.get("guard", {}))
        if method == "guard_tests_only":
            guard_cfg["diff_tests"] = False
        repair_fn = propose_fix if llm is not None else None
        guard = Guard(ws, llm, guard_cfg, repair_fn=repair_fn, graph=graph)
        emit("baseline", test_runs=ws.test_runs)
        check = guard.check_batch if on_event is None else report_checks(guard, ws, on_event)
        outcome = apply_with_bisection(batches, check)

        results = guard.results()
        results += [
            EditResult(i.item_id, "skipped", notes="suggest lane: reported, not applied")
            for i in plan.items
            if i not in safe
        ]
        counts = {
            s: sum(r.status == s for r in results) for s in ("kept", "repaired", "rolled_back")
        }
        diff_stats = ws.diff_stats(ws.base)
        usage = llm.usage() if llm is not None else {}
        stats = {
            "items_total": len(plan.items),
            "items_safe": len(safe),
            "items_kept": counts["kept"],
            "items_repaired": counts["repaired"],
            "items_rolled_back": counts["rolled_back"],
            "lines_removed": diff_stats["lines_removed"],
            "files_removed": diff_stats["files_removed"],
            "test_runs": ws.test_runs,
            "llm_calls": usage.get("llm_calls", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "llm_retries": usage.get("llm_retries", 0),
            "llm_failures": usage.get("llm_failures", 0),
            "llm_events": usage.get("llm_events", []),
            "wall_seconds": round(time.time() - t0, 2),
            "n_checks": outcome["n_checks"],
            "final_diff": ws.diff(ws.base),
            "scope": scope_report(ws.repo_id, ws.path, graph, cfg),
        }
        if on_event is not None:
            emit(
                "guard",
                since,
                outcome=outcome,
                results=to_dict(results),
                stats={k: v for k, v in stats.items() if k != "final_diff"},
            )
        report = SweepReport(ws.repo_id, method, "now", seed, started, _now(), plan, results, stats)
        if cfg.get("run_id"):
            save_json(
                report, report_path(core.get("out_dir", "results/raw"), cfg["run_id"], report)
            )
        emit("report", stats={k: v for k, v in stats.items() if k != "final_diff"})
        return report
    finally:
        # also on errors: a SWE-bench workspace holds a Docker container
        if not core.get("sandbox", {}).get("keep_workspace"):
            ws.close()
