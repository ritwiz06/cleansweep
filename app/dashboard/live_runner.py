"""Run one sweep and log every step, for the Live sweep page.

The sweep is cleansweep.workflow.run_sweep; its on_event callback (translate) turns each step and
Guard check into the page's events. Run from the repo root to record a run without the browser:
    python -m app.dashboard.live_runner --judge-mode gatekeeper
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import save_json, to_dict
from cleansweep.core.models import METHODS, SweepReport
from cleansweep.eval import run_hidden_checks, summarize
from cleansweep.runlog import fold, list_runs, read_events  # noqa: F401  (re-exported for the pages)
from cleansweep.workflow import run_sweep
from cleansweep.workflow.sweep import make_llm

ROOT = Path(__file__).resolve().parents[2]
LIVE_DIR = ROOT / "results" / "raw" / "live"
SHIPPED_DIR = ROOT / "demo" / "replay"
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
BASELINES = ("tools_only", "one_shot_llm", "one_shot_retry")
# run_sweep's step events, and the stage that starts after each
NEXT_STAGE = {
    "open": "analyze",
    "analyze": "plan",
    "plan": "rank",
    "rank": "batch",
    "batch": "guard",
}


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
        self.model = getattr(llm, "model", None)

    def _call(self, fn, messages, temperature, seed, extra_body):
        self._n += 1
        n = self._n
        self._log.emit("llm_start", n=n)
        start = time.time()
        try:
            if extra_body:
                return fn(messages, temperature, seed, extra_body=extra_body)
            return fn(messages, temperature, seed)
        finally:
            self._log.emit("llm_end", n=n, seconds=round(time.time() - start, 1))

    def chat(self, messages, temperature=0.0, seed=None, extra_body=None):
        return self._call(self._llm.chat, messages, temperature, seed, extra_body)

    def chat_json(self, messages, temperature=0.0, seed=None, extra_body=None):
        return self._call(self._llm.chat_json, messages, temperature, seed, extra_body)

    def usage(self) -> dict:
        return self._llm.usage()


def translate(log: EventLog) -> Callable[[str, dict], None]:
    """run_sweep's on_event callback: each step and Guard check becomes the page's event."""

    def on_event(name: str, payload: dict) -> None:
        if name in NEXT_STAGE or name == "guard":
            log.emit("stage_done", stage=name, **payload)
            if name in NEXT_STAGE:
                log.emit("stage_start", stage=NEXT_STAGE[name])
        elif name == "baseline":
            log.emit("guard_baseline", **payload)
        elif name == "check_start":
            log.emit("batch_start", **payload)
        elif name == "check":
            log.emit("batch_result", **payload)

    return on_event


def _run(target: str, cfg: dict, method: str, log: EventLog) -> SweepReport:
    if method in BASELINES:
        for stage in NEXT_STAGE:
            log.emit("stage_done", stage=stage, seconds=0, skipped=True)
        log.emit("stage_start", stage="guard")
        since = time.time()
        report = run_sweep(target, cfg, method)
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
    log.emit("stage_start", stage="open")
    llm = cfg.get("llm_client") or make_llm(cfg.get("core", {}))
    cfg = {**cfg, "llm_client": LoggedLLM(llm, log) if llm is not None else None}
    return run_sweep(target, cfg, method, on_event=translate(log))


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
            report = _run(target, cfg, method, log)

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


def shipped_runs(folder: str | Path = SHIPPED_DIR) -> list[Path]:
    """v1 recordings that ship with the repository (demo/replay/), newest run id first.

    v2 recordings (agent-team runs, for Studio) sit in the same folder and are left out."""
    found = []
    for path in Path(folder).glob("*/events.jsonl"):
        with path.open(encoding="utf-8") as f:
            if json.loads(f.readline() or "{}").get("v") != 2:
                found.append(path.parent)
    return sorted(found, reverse=True)


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
