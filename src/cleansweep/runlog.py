"""Recorded runs: v1 event logs (read, fold, list), saved sweep reports and answer-key scores.

The experiment scripts, the dashboard and Studio all read runs through these helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cleansweep.core.config import REPO_ROOT
from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

LIVE_DIR = REPO_ROOT / "results" / "raw" / "live"
REPORT_KEYS = {"repo_id", "method", "plan", "results", "stats"}


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


def fold(events: list[dict]) -> dict:
    """Turn a list of v1 live-sweep events into the state the Live sweep page draws."""
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


def is_sweep_report(path: str | Path) -> bool:
    """True if the file is a saved SweepReport (results/raw also holds timing and summary JSON)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and REPORT_KEYS <= set(data)


def load_report(path: str | Path) -> SweepReport:
    """A saved SweepReport."""
    return load_json(SweepReport, path)


def outcome_score(report: SweepReport, expected_path: str | Path) -> dict:
    """Compare what happened to each planted item with its expected_outcome."""
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))["items"]
    status = {r.item_id: r.status for r in report.results}
    by_key = {i.unit.key: status.get(i.item_id, "-") for i in report.plan.items}
    rows = []
    for row in expected:
        got = by_key.get(row["key"], "not found")
        actual = "applied" if got in ("kept", "repaired") else "not_applied"
        rows.append(
            {
                "unit": row["key"],
                "category": row["category"],
                "expected": row["expected_outcome"],
                "actual": actual,
                "guard status": got,
                "match": actual == row["expected_outcome"],
            }
        )
    table = pd.DataFrame(rows)
    return {"hits": int(table["match"].sum()), "total": len(table), "table": table}


def _hidden_from_log(path: Path) -> dict:
    # CLI runs saved with `> name.txt` end with "hidden checks: {...}"
    if not path.exists() or "hidden checks: " not in (text := path.read_text(errors="replace")):
        return {}
    data, _ = json.JSONDecoder().raw_decode(text.split("hidden checks: ", 1)[1])
    return data


def compare_reports(folder: str | Path) -> pd.DataFrame:
    """One row per saved sweep report in a folder, with hidden-check results when logged."""
    rows = []
    for path in sorted(Path(folder).glob("*.json")):
        if not is_sweep_report(path):
            continue
        report = load_report(path)
        hidden = _hidden_from_log(path.with_suffix(".txt"))
        stats = report.stats
        rows.append(
            {
                "run": path.stem,
                "method": report.method,
                "kept": stats.get("items_kept", 0) + stats.get("items_repaired", 0),
                "rolled back": stats.get("items_rolled_back", 0),
                "test runs": stats.get("test_runs", 0),
                "lines removed": stats.get("lines_removed", 0),
                "visible broken": hidden.get("visible_new_failures"),
                "hidden changed": hidden.get("behavior_changed"),
                "date": report.started_at[:10],
            }
        )
    return pd.DataFrame(rows)
