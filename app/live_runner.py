"""Run one sweep step by step and log every step, for the Live sweep page.

The steps and settings mirror cleansweep.workflow.sweep.run_sweep; keep the two in sync.
Run from the repo root to record a run without the browser:
    python -m app.live_runner --judge-mode gatekeeper
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.analysis import build_graph, extract_features
from cleansweep.core.config import load_config
from cleansweep.core.io import save_json, to_dict
from cleansweep.core.models import METHODS, EditResult, SweepReport
from cleansweep.eval import one_shot_llm, run_hidden_checks, summarize, tools_only
from cleansweep.guard import Guard
from cleansweep.llm import get_client
from cleansweep.ranking import load_ranker
from cleansweep.reviewer import build_plan, propose_fix
from cleansweep.sandbox import open_workspace
from cleansweep.scheduler import apply_with_bisection, make_batches

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "results" / "raw" / "live"
TOY_REPO = ROOT / "tests" / "fixtures" / "toy_repo"
STAGES = ["open", "analyze", "plan", "rank", "batch", "guard", "hidden", "done"]
STAGE_LABELS = {
    "open": "Open",
    "analyze": "Analyze",
    "plan": "Plan",
    "rank": "Rank",
    "batch": "Batch",
    "guard": "Guard",
    "hidden": "Hidden checks",
    "done": "Done",
}
JUDGE_MODES = ["gatekeeper", "advisory", "off"]
JUDGE_ENV = "CLEANSWEEP_JUDGE_MODE"
BASELINES = ("tools_only", "one_shot_llm")


class EventLog:
    """Appends events to a JSON-lines file; `t` is seconds since the log was opened."""

    def __init__(self, path: str | Path, on_event: Callable[[dict], None] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.t0 = time.time()
        self.on_event = on_event

    def emit(self, kind: str, **data) -> dict:
        event = {"t": round(time.time() - self.t0, 3), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        if self.on_event:
            self.on_event(event)
        return event


class _EventHandler(logging.Handler):
    def __init__(self, log: EventLog):
        super().__init__(logging.INFO)
        self.log = log

    def emit(self, record: logging.LogRecord) -> None:
        self.log.emit(
            "log", logger=record.name, level=record.levelname, message=record.getMessage()
        )


@contextmanager
def capture_logs(log: EventLog, name: str = "cleansweep"):
    """Copy INFO+ records from the cleansweep loggers into the run's events (the run log)."""
    logger = logging.getLogger(name)
    handler = _EventHandler(log)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(min(previous or logging.WARNING, logging.INFO))
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def read_events(path: str | Path) -> list[dict]:
    """Events from an events.jsonl file, in order; a half-written last line is skipped."""
    path = Path(path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return events


def replay(
    events: list[dict], speed: float = 10.0, tick: float = 0.25, sleep=time.sleep
) -> Iterator[tuple[float, int]]:
    """Play recorded events back in order.

    Yields (clock, n): the recorded time reached so far and how many events have happened.
    Waits the recorded gaps divided by `speed`, in steps of `tick` seconds so a page can redraw.
    """
    clock, n = 0.0, 0
    yield clock, n
    while n < len(events):
        next_t = events[n]["t"]
        while next_t - clock > tick * speed:
            sleep(tick)
            clock += tick * speed
            yield clock, n
        sleep(max(next_t - clock, 0.0) / speed)
        clock = next_t
        while n < len(events) and events[n]["t"] <= clock:
            n += 1
        yield clock, n


class LoggedLLM:
    """Passes calls to the real client and logs each request, so the page can show the judge."""

    def __init__(self, llm, log: EventLog):
        self._llm = llm
        self._log = log
        self._n = 0

    def _call(self, fn, messages, temperature, seed):
        self._n += 1
        n = self._n
        self._log.emit("llm_start", n=n)
        start = time.time()
        try:
            return fn(messages, temperature, seed)
        finally:
            self._log.emit("llm_end", n=n, seconds=round(time.time() - start, 1))

    def chat(self, messages, temperature=0.0, seed=None):
        return self._call(self._llm.chat, messages, temperature, seed)

    def chat_json(self, messages, temperature=0.0, seed=None):
        return self._call(self._llm.chat_json, messages, temperature, seed)

    def usage(self) -> dict:
        return self._llm.usage()


def logged_check_fn(guard, ws, log: EventLog) -> Callable[[list], bool]:
    """Wrap Guard.check_batch so every check, including bisection halves, is logged."""
    count = 0

    def check(batch) -> bool:
        nonlocal count
        count += 1
        log.emit(
            "batch_start",
            n=count,
            items=[i.item_id for i in batch],
            units=[i.unit.key for i in batch],
            categories=[i.category for i in batch],
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
        lines_removed = ws.diff_stats(ws.base)["lines_removed"]
        log.emit(
            "batch_result",
            n=count,
            ok=ok,
            result=result,
            statuses=statuses,
            tests=to_dict(tests) if tests is not None else None,
            ast_equal=ast_equal,
            probes=to_dict(probes) if probes is not None else None,
            test_runs=ws.test_runs,
            lines_removed=lines_removed,
            seconds=round(time.time() - start, 1),
        )
        return ok

    return check


def _make_llm(core: dict):
    # Same rule as cleansweep.workflow.sweep.make_llm (not exported by the package).
    llm_cfg = core.get("llm", {})
    enabled = llm_cfg.get("enabled", "auto")
    if enabled == "auto":
        enabled = bool(os.environ.get(llm_cfg.get("api_key_env", "VOYAGER_API_KEY")))
    return get_client(llm_cfg) if enabled else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sweep(target: str, cfg: dict, method: str, log: EventLog) -> SweepReport:
    started, t0 = _now(), time.time()
    core = cfg.get("core", {})
    exp = cfg.get("exp", {})

    def begin(stage: str) -> float:
        log.emit("stage_start", stage=stage)
        return time.time()

    def done(stage: str, since: float, **data) -> None:
        log.emit("stage_done", stage=stage, seconds=round(time.time() - since, 1), **data)

    since = begin("open")
    ws = open_workspace(target, core.get("sandbox"))
    real_llm = cfg.get("llm_client") or _make_llm(core)
    llm = LoggedLLM(real_llm, log) if real_llm is not None else None
    done("open", since, repo_id=ws.repo_id, workspace=ws.path, llm=getattr(real_llm, "model", None))

    try:
        since = begin("analyze")
        graph = build_graph(ws.path)
        features = extract_features(ws.path, graph)
        done("analyze", since, units=len(graph.units()))

        since = begin("plan")
        plan = build_plan(ws, graph, llm, use_llm=llm is not None)
        done("plan", since, items=to_dict(plan.items))

        since = begin("rank")
        if method != "no_ranker":
            load_ranker(exp.get("ranker_path")).score(plan.items, features)
            done("rank", since, scores={i.item_id: i.safe_score for i in plan.items})
        else:
            done("rank", since, skipped=True)

        since = begin("batch")
        safe = [i for i in plan.items if i.lane == "safe" and i.action != "report_only"]
        max_size = 1 if method == "no_batching" else exp.get("batch_max_size", 8)
        batches = make_batches(safe, max_size)
        done("batch", since, max_size=max_size, batches=[[i.item_id for i in b] for b in batches])

        since = begin("guard")
        guard_cfg = dict(core.get("guard", {}))
        if method == "guard_tests_only":
            guard_cfg["diff_tests"] = False
        repair_fn = propose_fix if llm is not None else None
        guard = Guard(ws, llm, guard_cfg, repair_fn=repair_fn, graph=graph)
        log.emit("guard_baseline", test_runs=ws.test_runs)
        outcome = apply_with_bisection(batches, logged_check_fn(guard, ws, log))

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
            "wall_seconds": round(time.time() - t0, 2),
            "n_checks": outcome["n_checks"],
            "final_diff": ws.diff(ws.base),
        }
        done(
            "guard",
            since,
            outcome=outcome,
            results=to_dict(results),
            stats={k: v for k, v in stats.items() if k != "final_diff"},
        )
        return SweepReport(ws.repo_id, method, "now", 0, started, _now(), plan, results, stats)
    finally:
        if not core.get("sandbox", {}).get("keep_workspace"):
            ws.close()


def _baseline(target: str, cfg: dict, method: str, log: EventLog) -> SweepReport:
    for stage in ("open", "analyze", "plan", "rank", "batch"):
        log.emit("stage_done", stage=stage, seconds=0, skipped=True)
    log.emit("stage_start", stage="guard")
    since = time.time()
    report = tools_only(target, cfg) if method == "tools_only" else one_shot_llm(target, cfg, 0)
    log.emit(
        "stage_done",
        stage="guard",
        seconds=round(time.time() - since, 1),
        baseline=True,
        items=to_dict(report.plan.items),
        results=to_dict(report.results),
        stats={k: v for k, v in report.stats.items() if k != "final_diff"},
    )
    return report


def run_live(
    target: str,
    cfg: dict | None = None,
    method: str = "cleansweep",
    judge_mode: str | None = None,
    run_id: str | None = None,
    out_dir: str | Path = LIVE_DIR,
    on_event: Callable[[dict], None] | None = None,
) -> tuple[SweepReport, Path]:
    """Run one sweep, log each step to <out_dir>/<run_id>/events.jsonl, save report.json there."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    if judge_mode is not None and judge_mode not in JUDGE_MODES:
        raise ValueError(f"judge mode must be one of {JUDGE_MODES}, got {judge_mode!r}")
    cfg = cfg or load_config()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = run_id or f"{stamp}_{Path(target).name}_{method}_{judge_mode or 'config'}"
    run_dir = Path(out_dir) / run_id
    log = EventLog(run_dir / "events.jsonl", on_event)

    previous = os.environ.get(JUDGE_ENV)
    if judge_mode:
        os.environ[JUDGE_ENV] = judge_mode
    try:
        log.emit(
            "run_start",
            run_id=run_id,
            target=str(target),
            method=method,
            judge_mode=os.environ.get(JUDGE_ENV) or "config",
            model=os.environ.get("VOYAGER_MODEL"),
        )
        with capture_logs(log):
            if method in BASELINES:
                report = _baseline(target, cfg, method, log)
            else:
                report = _sweep(target, cfg, method, log)

        log.emit("stage_start", stage="hidden")
        since = time.time()
        hidden = run_hidden_checks(str(target), report.stats.get("final_diff", ""), cfg)
        summary = summarize(report, hidden)
        log.emit(
            "stage_done",
            stage="hidden",
            seconds=round(time.time() - since, 1),
            hidden=hidden,
            summary=summary,
        )
        save_json(report, run_dir / "report.json")
        log.emit("stage_done", stage="done", seconds=0, report=str(run_dir / "report.json"))
        return report, run_dir
    except Exception as exc:
        log.emit("error", message=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if previous is None:
            os.environ.pop(JUDGE_ENV, None)
        else:
            os.environ[JUDGE_ENV] = previous


def fold(events: list[dict]) -> dict:
    """Turn a list of events into the state the page draws."""
    state: dict = {
        "run": {},
        "stages": {},
        "stage_seconds": {},
        "current": None,
        "current_since": 0.0,
        "items": [],
        "scores": {},
        "batches": [],
        "llm": [],
        "results": [],
        "stats": {},
        "outcome": {},
        "hidden": None,
        "summary": None,
        "report": None,
        "error": None,
        "logs": [],
        "statuses": {},
        "test_runs": 0,
        "lines_removed": 0,
        "t": 0.0,
    }
    for event in events:
        kind = event["kind"]
        state["t"] = event["t"]
        if kind == "run_start":
            state["run"] = event
        elif kind == "stage_start":
            state["stages"][event["stage"]] = "running"
            state["current"], state["current_since"] = event["stage"], event["t"]
        elif kind == "stage_done":
            stage = event["stage"]
            state["stages"][stage] = "skipped" if event.get("skipped") else "done"
            state["stage_seconds"][stage] = event.get("seconds", 0)
            if state["current"] == stage:
                state["current"] = None
            for key in ("items", "scores", "results", "stats", "outcome", "hidden", "summary"):
                if key in event:
                    state[key] = event[key]
            if "report" in event:
                state["report"] = event["report"]
        elif kind == "guard_baseline":
            state["test_runs"] = event["test_runs"]
        elif kind == "llm_start":
            state["llm"].append({"n": event["n"], "start": event["t"], "seconds": None})
        elif kind == "llm_end":
            for call in state["llm"]:
                if call["n"] == event["n"]:
                    call["seconds"] = event["seconds"]
        elif kind == "batch_start":
            state["batches"].append({**event, "start": event["t"], "result": None})
        elif kind == "batch_result":
            card = next(b for b in reversed(state["batches"]) if b["n"] == event["n"])
            card.update(
                {k: v for k, v in event.items() if k not in ("kind", "t", "n")},
                end=event["t"],
            )
            state["statuses"].update(event["statuses"])
            state["test_runs"] = event["test_runs"]
            if event.get("lines_removed") is not None:
                state["lines_removed"] = event["lines_removed"]
        elif kind == "log":
            state["logs"].append(event)
        elif kind == "error":
            state["error"] = event["message"]
    if state["stats"]:
        state["test_runs"] = state["stats"].get("test_runs", state["test_runs"])
        state["lines_removed"] = state["stats"].get("lines_removed", state["lines_removed"])
    if state["results"]:
        state["statuses"] = {r["item_id"]: r["status"] for r in state["results"]}
    values = list(state["statuses"].values())
    state["kept"] = values.count("kept") + values.count("repaired")
    state["rolled_back"] = values.count("rolled_back")
    return state


def list_runs(out_dir: str | Path = LIVE_DIR) -> list[Path]:
    """Saved live runs (folders with an events.jsonl), newest first."""
    found = [p.parent for p in Path(out_dir).glob("*/events.jsonl")]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one live sweep and record its events.")
    parser.add_argument("--target", default=str(TOY_REPO))
    parser.add_argument("--method", default="cleansweep", choices=METHODS)
    parser.add_argument("--judge-mode", choices=JUDGE_MODES)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    report, run_dir = run_live(args.target, None, args.method, args.judge_mode, args.run_id)
    print(f"{run_dir}  kept={report.stats['items_kept']} test_runs={report.stats['test_runs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
