from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_report.json"


REPORT_KEYS = {"repo_id", "method", "plan", "results", "stats"}
JUDGE_LINE = re.compile(r"^llm judge: (\w+) \(confidence ([\d.]+|None)\)")


def is_sweep_report(path: str | Path) -> bool:
    """True if the file is a saved SweepReport (results/raw also holds timing and summary JSON)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and REPORT_KEYS <= set(data)


def find_reports(raw_dir: str | Path = ROOT / "results" / "raw") -> list[Path]:
    """Saved sweep reports, newest first; the sample report if there are none yet."""
    found = [p for p in Path(raw_dir).rglob("*.json") if is_sweep_report(p)]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found or [SAMPLE]


def load_report(path: str | Path) -> SweepReport:
    return load_json(SweepReport, path)


def plan_table(report: SweepReport) -> pd.DataFrame:
    """One row per plan item with its Guard status."""
    status = {r.item_id: r.status for r in report.results}
    rows = [
        {
            "status": status.get(i.item_id, "-"),
            "lane": i.lane,
            "category": i.category,
            "unit": i.unit.key,
            "reason": i.reason,
            "evidence": "; ".join(i.evidence),
            "safe_score": i.safe_score,
            "item_id": i.item_id,
        }
        for i in report.plan.items
    ]
    return pd.DataFrame(rows)


def slop_meter(report: SweepReport) -> dict:
    """Items cleaned vs. still open (rolled back or only suggested)."""
    status = [r.status for r in report.results]
    cleaned = status.count("kept") + status.count("repaired")
    return {
        "cleaned": cleaned,
        "open": len(report.plan.items) - cleaned,
        "lines_removed": report.stats.get("lines_removed", 0),
    }


def restore_command(evidence: list[str], unit_path: str) -> str | None:
    """Shell command to bring back a quarantined file, if the item deleted one."""
    for line in evidence:
        if line.startswith("quarantined at "):
            return f"cp '{line.removeprefix('quarantined at ')}' '{unit_path}'"
    return None


def judge_decision(evidence: list[str]) -> tuple[str, float | None]:
    """The LLM judge's last decision and confidence recorded in an item's evidence."""
    for line in reversed(evidence):
        if m := JUDGE_LINE.match(line):
            return m.group(1), None if m.group(2) == "None" else float(m.group(2))
    return "-", None


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


SUMMARY = Path(__file__).resolve().parents[2] / "results" / "summary" / "v1"


def load_replay(folder: str | Path = SUMMARY) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """The Scheduler replay table and curves (scripts/experiments/v1/exp_replay.py), or None
    if missing."""
    folder = Path(folder)
    table, curves = folder / "scheduler_replay.csv", folder / "scheduler_curves.csv"
    return (
        pd.read_csv(table) if table.exists() else None,
        pd.read_csv(curves) if curves.exists() else None,
    )


def repos_label(repos: int, excluded: int = 0) -> str:
    """ "20 of 21 runnable repos (1 excluded)" when runnable repos were left out (DECISIONS)."""
    if not excluded:
        return f"{repos} runnable repos"
    return f"{repos} of {repos + excluded} runnable repos ({excluded} excluded)"


def policy_summary(replay: pd.DataFrame) -> pd.DataFrame:
    """Mean per policy over repositories."""
    cols = ["sweeps", "test_runs_est", "slop_debt_per_commit", "final_slop", "resurrection_rate"]
    out = replay.groupby("policy", sort=False)[cols].mean().round(3).reset_index()
    out.insert(1, "repositories", replay.groupby("policy", sort=False).size().values)
    return out


DATA_SUMMARY = ROOT / "results" / "data_summary"
EXPERIMENTS = {
    "mutation": "mutants",
    "patchdiff_recall": "PatchDiff recall (patch vs. developer's fix)",
    "false_alarm": "false alarms on identical copies",
}


def load_csv(name: str, folder: str | Path = SUMMARY) -> pd.DataFrame | None:
    """A results CSV (summary or data_summary), or None when it hasn't been made yet."""
    path = Path(folder) / name
    return pd.read_csv(path) if path.exists() else None


def guard_strength_table(rows: pd.DataFrame) -> pd.DataFrame:
    """guard_strength.csv for reading: what the tests catch and what only the probes catch."""
    out = rows.copy()
    if "probe_mode" not in out:
        out["probe_mode"] = "direct"
    out["experiment"] = out.experiment.map(EXPERIMENTS).fillna(out.experiment)
    out["caught"] = out.caught.astype(str) + " / " + out.n.astype(str)
    out = out.rename(
        columns={
            "target_set": "target set",
            "probe_mode": "probe mode",
            "caught_by_tests": "by tests",
            "caught_by_probes": "only by probes",
        }
    )
    return out[["target set", "experiment", "probe mode", "caught", "by tests", "only by probes"]]


def false_alarms(rows: pd.DataFrame) -> pd.DataFrame:
    """The false-alarm rows of guard_strength.csv."""
    table = guard_strength_table(rows[rows.experiment == "false_alarm"])
    table = table.drop(columns=["experiment", "by tests", "only by probes"])
    return table.rename(columns={"caught": "false alarms / checks"})


def top_rules(rules: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """The association rules with the highest lift (ties: higher support first)."""
    out = rules.sort_values(["lift", "support"], ascending=False).head(n)
    return out.assign(
        support=out.support.round(3), confidence=out.confidence.round(2), lift=out.lift.round(2)
    ).reset_index(drop=True)


def funnel_stages(funnel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The AIDev selection funnel split into its stages and the drop reasons."""
    dropped = funnel.stage.str.startswith("dropped: ")
    reasons = funnel[dropped].assign(stage=funnel[dropped].stage.str.removeprefix("dropped: "))
    reasons = reasons.rename(columns={"stage": "drop reason"})[["drop reason", "count"]]
    return funnel[~dropped].reset_index(drop=True), reasons.reset_index(drop=True)
