from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.analysis import build_graph, extract_features
from cleansweep.core.io import save_json
from cleansweep.core.models import EditResult, SweepReport
from cleansweep.guard import Guard
from cleansweep.llm import get_client
from cleansweep.ranking import load_ranker
from cleansweep.reviewer import build_plan, propose_fix
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


def run_sweep(target: str, cfg: dict, method: str = "cleansweep", seed: int = 0) -> SweepReport:
    """Open, analyze, plan, rank, batch and guard one target; return the sweep report."""
    if method in ("tools_only", "one_shot_llm", "one_shot_retry"):
        from cleansweep import eval as baselines

        if method == "tools_only":
            return baselines.tools_only(target, cfg)
        if method == "one_shot_retry":
            return baselines.one_shot_retry(target, cfg, seed)
        return baselines.one_shot_llm(target, cfg, seed)

    started, t0 = _now(), time.time()
    core = cfg.get("core", {})
    exp = cfg.get("exp", {})
    ws = open_workspace(target, core.get("sandbox"))
    try:
        llm = cfg.get("llm_client") or make_llm(core)

        graph = build_graph(ws.path)
        features = extract_features(ws.path, graph)
        plan = build_plan(ws, graph, llm, use_llm=llm is not None)
        if method != "no_ranker":
            load_ranker(exp.get("ranker_path")).score(plan.items, features)

        safe = [i for i in plan.items if i.lane == "safe" and i.action != "report_only"]
        max_size = 1 if method == "no_batching" else exp.get("batch_max_size", 8)
        guard_cfg = dict(core.get("guard", {}))
        if method == "guard_tests_only":
            guard_cfg["diff_tests"] = False
        repair_fn = propose_fix if llm is not None else None
        guard = Guard(ws, llm, guard_cfg, repair_fn=repair_fn, graph=graph)
        outcome = apply_with_bisection(make_batches(safe, max_size), guard.check_batch)

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
        }
        report = SweepReport(ws.repo_id, method, "now", seed, started, _now(), plan, results, stats)
        if cfg.get("run_id"):
            save_json(
                report, report_path(core.get("out_dir", "results/raw"), cfg["run_id"], report)
            )
        return report
    finally:
        # also on errors: a SWE-bench workspace holds a Docker container
        if not core.get("sandbox", {}).get("keep_workspace"):
            ws.close()
