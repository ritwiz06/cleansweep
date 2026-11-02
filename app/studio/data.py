"""Studio's read-only data: results tables, case studies, watch logs and the dashboard pages."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from cleansweep.runlog import compare_reports, load_report, outcome_score

from . import files
from .files import ROOT

REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)"
CASE_DOCS = ["CLEANUP_REPORT.md", "diffstat.txt", "review_sheet.md", "blueprint.md"]
GUARD_EXPERIMENTS = {
    "mutation": "mutants",
    "patchdiff_recall": "PatchDiff recall (patch vs. developer's fix)",
    "false_alarm": "false alarms on identical copies",
}
POLICY_COLUMNS = [
    "sweeps",
    "test_runs_est",
    "slop_debt_per_commit",
    "final_slop",
    "resurrection_rate",
]


def table(df: pd.DataFrame | None) -> dict | None:
    """A DataFrame as {"columns", "rows"} with JSON-safe values (NaN -> null)."""
    if df is None:
        return None
    data = json.loads(df.to_json(orient="split", index=False))
    return files.clean({"columns": data["columns"], "rows": data["data"]})


def read_csv(path: Path) -> pd.DataFrame | None:
    """A CSV as a DataFrame, or None when it is missing, empty or unreadable."""
    try:
        return pd.read_csv(path) if path.is_file() and path.stat().st_size else None
    except (OSError, ValueError):
        return None


def results_index(results: Path) -> dict:
    """The tables and figures under results/summary/<v> and results/figures/<v>."""
    out = {}
    for version in ("v1", "v2"):
        summary, figures = results / "summary" / version, results / "figures" / version
        out[version] = {
            "tables": sorted(p.name for p in summary.glob("*.csv")) if summary.is_dir() else [],
            "notes": sorted(p.name for p in summary.glob("*.md")) if summary.is_dir() else [],
            "figures": sorted(p.name for p in figures.glob("*.png")) if figures.is_dir() else [],
        }
    return out


def _cases_dir(results: Path) -> Path:
    return results / "raw" / "case_studies"


def _reviews(folder: Path) -> dict:
    record = files.read_json(folder / "llm_review.json") or {}
    return record.get("reviews") or {}


def _review_links(base: Path) -> dict[str, Path]:
    """Run folder name -> the folder whose review sheet names it as its safe or thorough run."""
    links: dict[str, Path] = {}
    for path in sorted(base.glob("*/review_rows.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for mode in ("safe", "thorough"):
            if isinstance(meta, dict) and isinstance(meta.get(mode), str):
                links.setdefault(meta[mode], path.parent)
    return links


def _review(base: Path, name: str, links: dict[str, Path]) -> tuple[Path | None, dict, dict]:
    """A case study's review folder, rows and LLM reviews: its own sheet, else this run's rows
    from the sheet that names it."""
    own = base / name
    if (own / "review_rows.json").is_file():
        return own, files.read_json(own / "review_rows.json") or {}, _reviews(own)
    folder = links.get(name)
    if folder is None:
        return None, {}, {}
    meta = files.read_json(folder / "review_rows.json") or {}
    rows = [r for r in meta.get("rows", []) if r.get("run") == name]
    reviews = _reviews(folder)
    return (
        folder,
        {**meta, "rows": rows},
        {str(r.get("n")): reviews.get(str(r.get("n")), {}) for r in rows},
    )


def case_list(results: Path) -> list[dict]:
    """One row per case study: project, verdict, tests before/after, size of the change."""
    base = _cases_dir(results)
    links = _review_links(base) if base.is_dir() else {}
    rows = []
    for path in sorted(base.glob("*/summary.json")) if base.is_dir() else []:
        s = files.read_json(path) or {}
        folder, _, reviews = _review(base, path.parent.name, links)
        decisions = [r.get("decision") for r in reviews.values() if r.get("decision")]
        rows.append(
            {
                "name": path.parent.name,
                "project": s.get("project"),
                "verdict": s.get("verdict"),
                "seconds": s.get("seconds"),
                "candidates": s.get("candidates"),
                "packages": s.get("packages"),
                "lines_removed": s.get("lines_removed"),
                "files_removed": s.get("files_removed"),
                "tests_before": (s.get("tests_before") or {}).get("passed"),
                "tests_after": (s.get("tests_after") or {}).get("passed"),
                "has_review": folder is not None and (folder / "review_sheet.md").is_file(),
                "reviewed": len(decisions),
                "accepted": decisions.count("accept"),
                "rejected": decisions.count("reject"),
            }
        )
    return rows


def case_detail(results: Path, name: str) -> dict:
    """A case study: its summary, documents, and review rows with the LLM reviewer's decisions."""
    folder = files.resolve({"cases": _cases_dir(results)}, "cases", name)
    if not (folder / "summary.json").is_file():
        raise FileNotFoundError(f"no case study {name}")
    s = files.read_json(folder / "summary.json") or {}
    s.pop("workspace", None)
    brief = s.pop("brief", None) or {}
    docs = {n: files.read_text(folder / n)["text"] for n in CASE_DOCS if (folder / n).is_file()}
    base = _cases_dir(results)
    review_folder, meta, reviews = _review(base, folder.name, _review_links(base))
    if review_folder is not None and (review_folder / "review_sheet.md").is_file():
        docs["review_sheet.md"] = files.read_text(review_folder / "review_sheet.md")["text"]
    rows = []
    for row in meta.get("rows", []):
        review = reviews.get(str(row.get("n")), {})
        rows.append(
            {
                **row,
                "llm_decision": review.get("decision"),
                "llm_votes": review.get("votes"),
                "llm_reason": review.get("reason"),
            }
        )
    record = (files.read_json(review_folder / "llm_review.json") if review_folder else None) or {}
    return {
        "name": name,
        "summary": s,
        "brief": {k: brief.get(k) for k in ("name", "languages", "python_files", "test_files")},
        "docs": docs,
        "has_final_diff": (folder / "final.diff").is_file(),
        "review": {
            "label": REVIEW_LABEL,
            "model": record.get("model"),
            "runs": {"safe": meta.get("safe"), "thorough": meta.get("thorough")},
            "rows": rows,
        },
    }


def watch_log(folder: Path) -> dict:
    """A watch folder: one entry per poll, the saved state, and its clean runs."""
    entries = []
    path = folder / "watch_log.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            entries.append(json.loads(line))
        except ValueError:
            break
    runs = sorted(p.parent.name for p in folder.glob("*/events.jsonl"))
    return files.clean(
        {"entries": entries, "state": files.read_json(folder / "watch_state.json"), "runs": runs}
    )


def scheduler(results: Path, repo: str | None = None) -> dict:
    """The Scheduler page: policy means, trade-off, and one repository's replay and curves."""
    summary = results / "summary" / "v1"
    replay = read_csv(summary / "scheduler_replay.csv")
    if replay is None:
        return {"replay": None}
    cfg = yaml.safe_load((ROOT / "configs" / "data.yaml").read_text()) or {}
    excluded = int((cfg.get("aidev") or {}).get("excluded_runnable", 0))
    means = replay.groupby("policy", sort=False)[POLICY_COLUMNS].mean().round(3).reset_index()
    means.insert(1, "repositories", replay.groupby("policy", sort=False).size().values)
    repos = sorted(replay.repo.unique())
    repo = repo if repo in repos else repos[0]
    curves = read_csv(summary / "scheduler_curves.csv")
    mine = None
    if curves is not None:
        mine = curves[curves.repo == repo][["policy", "index", "open_slop", "swept"]]
        mine = mine.assign(swept=mine.swept.astype(str) == "True")
    tradeoff = read_csv(summary / "scheduler_tradeoff.csv")
    if tradeoff is not None:
        tradeoff = tradeoff.drop(columns=["repo_set"], errors="ignore")
    return {
        "repos_count": int(replay.repo.nunique()),
        "excluded": excluded,
        "means": table(means),
        "tradeoff": table(tradeoff),
        "figure": _figure(results, "v1", "scheduler_tradeoff.png"),
        "repos": repos,
        "repo": repo,
        "policies": [p for p in replay.policy.unique() if p != "none"],
        "replay": table(replay[replay.repo == repo].drop(columns=["repo"])),
        "curves": table(mine),
    }


def _figure(results: Path, version: str, name: str) -> str | None:
    return f"figures/{version}/{name}" if (results / "figures" / version / name).is_file() else None


def baselines(results: Path) -> dict:
    """The Baselines page: main table, paired tests and ablations."""
    summary = results / "summary" / "v1"
    return {
        "main": table(read_csv(summary / "main_table.csv")),
        "paired": table(read_csv(summary / "paired_tests.csv")),
        "ablation": table(read_csv(summary / "ablation.csv")),
        "figure": _figure(results, "v1", "main_lines_removed.png"),
    }


def data_page(results: Path) -> dict:
    """The Data page: SWE-bench and PatchDiff counts, tiers, AIDev funnel, taxonomy, rules."""
    folder = results / "data_summary"
    funnel = read_csv(folder / "aidev_funnel.csv")
    stages = reasons = None
    if funnel is not None:
        dropped = funnel.stage.str.startswith("dropped: ")
        reasons = funnel[dropped].assign(stage=funnel[dropped].stage.str.removeprefix("dropped: "))
        reasons = reasons.rename(columns={"stage": "drop reason"})[["drop reason", "count"]]
        stages = funnel[~dropped].reset_index(drop=True)
    rules = read_csv(folder / "aidev_rules.csv")
    if rules is not None:
        rules = rules.sort_values(["lift", "support"], ascending=False).head(10)
        rules = rules.assign(
            support=rules.support.round(3),
            confidence=rules.confidence.round(2),
            lift=rules.lift.round(2),
        )
    taxonomy = read_csv(folder / "aidev_taxonomy.csv")
    if taxonomy is not None:
        taxonomy = taxonomy[["cluster", "size", "top_terms", "examples"]]
    return {
        "counts": table(read_csv(folder / "swebench_patchdiff.csv")),
        "tiers": table(read_csv(folder / "tiers.csv")),
        "funnel": table(stages),
        "drop_reasons": table(reasons),
        "taxonomy": table(taxonomy),
        "rules": table(rules),
        "detection": table(read_csv(folder / "detection_by_category.csv")),
    }


def guard(results: Path) -> dict:
    """The Guard page: caught by tests vs. only by probes, and the false alarms."""
    rows = read_csv(results / "summary" / "v1" / "guard_strength.csv")
    if rows is None:
        return {"strength": None, "false_alarms": None, "figure": None}
    out = rows.copy()
    if "probe_mode" not in out:
        out["probe_mode"] = "direct"
    alarms = out.experiment == "false_alarm"
    out["experiment"] = out.experiment.map(GUARD_EXPERIMENTS).fillna(out.experiment)
    out["caught"] = out.caught.astype(str) + " / " + out.n.astype(str)
    out = out.rename(
        columns={
            "target_set": "target set",
            "probe_mode": "probe mode",
            "caught_by_tests": "by tests",
            "caught_by_probes": "only by probes",
        }
    )
    cols = ["target set", "experiment", "probe mode", "caught", "by tests", "only by probes"]
    false = out[alarms][["target set", "probe mode", "caught"]]
    return {
        "strength": table(out[~alarms][cols]),
        "false_alarms": table(false.rename(columns={"caught": "false alarms / checks"})),
        "figure": _figure(results, "v1", "guard_strength.png"),
    }


def answer_key(target: str) -> Path | None:
    """A v1 run target's answer key in this repository: next to the target, or demo/'s copy."""
    path = Path(target.rstrip("/"))
    if not path.is_absolute():
        path = ROOT / path
    keys = [Path(f"{path}_expected.json"), ROOT / "demo" / f"{path.name}_expected.json"]
    root = ROOT.resolve()
    return next((k for k in keys if k.is_file() and k.resolve().is_relative_to(root)), None)


def sweep_score(folder: Path, target: str) -> dict | None:
    """A v1 run's outcome against its answer key, when it has a report and a key."""
    key = answer_key(target or "")
    if key is None or not (folder / "report.json").is_file():
        return None
    score = outcome_score(load_report(folder / "report.json"), key)
    return {"hits": score["hits"], "total": score["total"], "table": table(score["table"])}


def toy_runs(results: Path) -> dict | None:
    """The saved toy repo sweeps (results/raw/toy), one row each."""
    folder = results / "raw" / "toy"
    return table(compare_reports(folder)) if folder.is_dir() else None
