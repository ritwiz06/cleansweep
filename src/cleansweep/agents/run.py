"""Entry points: run_agentic (run_sweep with method="agentic") and clean_project (`clean`)."""

from __future__ import annotations

import copy
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.analysis.graph import iter_py_files
from cleansweep.core.io import save_json
from cleansweep.core.models import CleanupPlan, EditResult, SweepReport
from cleansweep.reviewer.planner import scope_report
from cleansweep.sandbox import open_workspace
from cleansweep.sandbox.local import default_work_dir

from .delivery import default_out, inside, prepare_workspace
from .llm import AgentLLM
from .runtime import Runtime
from .team import run_team

USER_CACHE = Path.home() / ".cache" / "cleansweep"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _make_llm(cfg: dict):
    from cleansweep.workflow.sweep import make_llm

    return cfg.get("llm_client") or make_llm(cfg.get("core", {}))


def build_report(rt, started: str, t0: float, seed: int = 0) -> SweepReport:
    """The run as a SweepReport, so v1's collection and statistics scripts read it unchanged."""
    items = list(rt.items.values())
    results = list(rt.results.values())
    for item in items:
        if item.item_id not in rt.results:
            why = (
                "dry run: planned, not applied"
                if rt.dry_run and item.lane == "safe"
                else f"{item.lane} lane: reported, not applied"
            )
            if item.lane == "safe" and not rt.dry_run:
                why = f"not applied: {rt.stopped or 'not reached'}"
            results.append(EditResult(item.item_id, "skipped", notes=why))
    counts = {s: sum(r.status == s for r in results) for s in ("kept", "repaired", "rolled_back")}
    diff = rt.ws.diff_stats(rt.ws.base)
    llm = rt.llm if rt.llm is not None else rt.manager_llm  # the scenario runs: Manager only
    usage = llm.usage() if llm is not None else {}
    stats = {
        "items_total": len(items),
        "items_safe": sum(i.lane == "safe" and i.action != "report_only" for i in items),
        "items_kept": counts["kept"],
        "items_repaired": counts["repaired"],
        "items_rolled_back": counts["rolled_back"],
        "lines_removed": diff["lines_removed"],
        "files_removed": diff["files_removed"],
        "test_runs": rt.ws.test_runs,
        "llm_calls": usage.get("requests", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "llm_retries": usage.get("llm_retries", 0),
        "llm_failures": usage.get("llm_failures", 0),
        "llm_events": usage.get("llm_events", []),
        "wall_seconds": round(time.time() - t0, 2),
        "n_checks": rt.checks,
        "final_diff": rt.ws.diff(rt.ws.base),
        "scope": scope_report(rt.ws.repo_id, rt.ws.path, rt.graph, rt.cfg),
        "agentic": {
            "mode": rt.mode,
            "ablation": rt.ablation,
            "verdict": rt.summary.get("verdict"),
            "phases": rt.phases.order(),
            "phase_seconds": rt.phases.seconds(),
            "back_steps": dict(rt.phases.back_steps),
            "agents": rt.agent_stats(),
            "llm_by_agent": usage.get("by_agent", {}),
            "messages": len(rt.board.messages),
            "artifacts": len(rt.cache.ids()),
            "lessons": rt.lessons.lessons,
            "decisions": {
                d: sum(v["decision"] == d for v in rt.verdicts.values())
                for d in ("safe", "suggest", "drop")
            },
            "budget_exhausted": sum(v.get("stop") == "budget" for v in rt.verdicts.values()),
            "packages": [
                {
                    "package": p.package_id,
                    "goal": p.goal,
                    "status": p.status,
                    "items": p.items,
                    "commit": p.commit,
                    "turns": p.turns,
                }
                for p in rt.packages
            ],
            "baseline": {k: v for k, v in (rt.baseline or {}).items() if k != "result"},
            "final": rt.final,
            "stopped": rt.stopped,
            "secrets": {"files": len(rt.secrets["files"]), "findings": len(rt.secrets["findings"])},
            "run_dir": str(rt.out),
            "branch": rt.branch,
        },
    }
    plan = CleanupPlan(rt.ws.repo_id, started, items)
    return SweepReport(rt.ws.repo_id, "agentic", "now", seed, started, _now(), plan, results, stats)


def run_agentic(
    target: str, cfg: dict, seed: int = 0, on_event: Callable[[str, dict], None] | None = None
) -> SweepReport:
    """run_sweep(..., method="agentic"): the agent team on one target, for experiments."""
    started, t0 = _now(), time.time()
    core = cfg.get("core", {})
    ws = open_workspace(target, core.get("sandbox"))
    try:
        out = cfg.get("agent_out") or tempfile.mkdtemp(
            prefix="cs_agentic_", dir=_ensure(default_work_dir(core.get("sandbox") or {}))
        )
        rt = Runtime(
            ws, cfg, _make_llm(cfg), out, run_id=cfg.get("run_id") or "agentic", v1_hook=on_event
        )
        rt.workspace_info = {}
        rt.make_patches = False
        run_team(rt)
        report = build_report(rt, started, t0, seed)
        if cfg.get("run_id"):
            from cleansweep.workflow.sweep import report_path

            save_json(
                report, report_path(core.get("out_dir", "results/raw"), cfg["run_id"], report)
            )
        if on_event is not None:
            on_event(
                "guard",
                {
                    "results": [],
                    "stats": {k: v for k, v in report.stats.items() if k != "final_diff"},
                    "seconds": 0.0,
                },
            )
            on_event(
                "report", {"stats": {k: v for k, v in report.stats.items() if k != "final_diff"}}
            )
        return report
    finally:
        if not core.get("sandbox", {}).get("keep_workspace"):
            ws.close()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_config(cfg: dict, out: Path) -> dict:
    """The run's config with every write location outside the project: quarantine in the
    output folder, LLM and probe caches in the user's cache folder (unless set absolute)."""
    cfg = copy.deepcopy(cfg)
    core = cfg.setdefault("core", {})
    sandbox = core.setdefault("sandbox", {})
    sandbox["quarantine_dir"] = str(out / "quarantine")
    llm = core.setdefault("llm", {})
    if not Path(llm.get("cache_path") or "x").is_absolute():
        llm["cache_path"] = str(USER_CACHE / "llm_cache.sqlite")
    guard = core.setdefault("guard", {})
    if not Path(guard.get("probe_cache_dir") or "x").is_absolute():
        guard["probe_cache_dir"] = str(USER_CACHE / "probes")
    return cfg


def clean_project(
    path: str,
    cfg: dict,
    out: str | None = None,
    mode: str | None = None,
    dry_run: bool = False,
    approve: Callable[[str], bool] | None = None,
    on_event: Callable[[dict], None] | None = None,
    llm=None,
    use_llm: bool = True,
    test_args: list[str] | None = None,
    exclude: list[str] | None = None,
    manager_llm=None,
) -> dict:
    """`cleansweep clean <path>`: clean a scratch copy of a project and deliver a branch.

    Returns {"out", "workspace", "branch", "summary", "files", "report"}. The original folder is
    never written to. manager_llm gives the Manager its own LLM (the scenario experiments run
    the other agents without one)."""
    src = Path(path).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"no such folder: {path}")
    if not iter_py_files(str(src)):
        raise ValueError(f"no Python files in {src}")
    out_dir = Path(out).expanduser().resolve() if out else default_out(src)
    if inside(out_dir, src):
        raise ValueError(
            f"--out must be outside the project folder ({src}); the original is never changed"
        )
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"the output folder is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    started, t0 = _now(), time.time()
    cfg = clean_config(cfg, out_dir)
    if exclude:
        reviewer = cfg.setdefault("reviewer", {})
        reviewer["exclude"] = [*reviewer.get("exclude", []), *exclude]
    ws, info = prepare_workspace(src, out_dir / "workspace", cfg["core"].get("sandbox"))
    ws.pytest_args = list(test_args or [])
    client = (llm or _make_llm(cfg)) if use_llm else None
    rt = Runtime(
        ws,
        cfg,
        client,
        out_dir,
        run_id=out_dir.name,
        on_event=on_event,
        mode=mode,
        dry_run=dry_run,
        approve=approve,
    )
    rt.workspace_info = info
    rt.make_patches = True
    if manager_llm is not None:
        rt.manager_llm = AgentLLM(manager_llm, rt.redact, rt.log, rt.run_budget)
    run_team(rt)
    report = build_report(rt, started, t0)
    save_json(report, out_dir / "report.json")
    return {
        "out": str(out_dir),
        "workspace": ws.path,
        "base": ws.base,
        "branch": rt.branch,
        "summary": rt.summary,
        "files": [str(out_dir / f) for f in rt.files],
        "report": report,
    }
