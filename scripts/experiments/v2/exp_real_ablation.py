"""The real-project ablation, the test of whether investigation helps on real projects: the team,
the no research squad and the single agent clean five real projects (this repository,
slop-guard, Skill_Seekers, shotgun and Telegram-Snowball-Sampling) in safe mode, at most 120
minutes each (exp_case_study.py --ablation). Records: results/raw/case_studies/
<project>-abl-<team | no_research | single_agent>/.

    python scripts/experiments/v2/exp_real_ablation.py review
    python scripts/experiments/v2/exp_real_ablation.py ui
    python scripts/experiments/v2/exp_real_ablation.py collect
    python scripts/experiments/v2/exp_real_ablation.py table

review: a review sheet of each run's kept changes (exp_review_sheet.py) and the independent,
blinded LLM reviewer's 3 votes on each kept change (exp_llm_review.py, no suggestions); its
acceptance is LLM-judged, not a human evaluation.
ui: shotgun's UI check (cleansweep.guard.ui_check) on each shotgun run's final diff, in its
container, so the three methods get the same check (the single agent has none of its own).
Writes ui_check.json beside the run's record.
collect: results/summary/v2/real_ablation_runs.csv, one row per run: verdict, packages kept and
rolled back, lines removed (deleted minus added) and files deleted in its final diff, the LLM
reviewer's accept / reject / unsure on the kept changes, the diff audit's kept code edits with the
confirmed wrong and debatable ones (diff_audit_checks.csv), the UI check, LLM requests, tokens and
minutes.
table: results/summary/v2/real_ablation.{csv,md}, per method, from real_ablation_runs.csv only
(offline; reproduce_tables.sh runs it).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# CLEANSWEEP_RESULTS points the table at another results folder (reproduce_tables.sh DIR)
RESULTS = Path(os.environ.get("CLEANSWEEP_RESULTS", ROOT / "results"))
SUMMARY = RESULTS / "summary" / "v2"
CASES = ROOT / "results" / "raw" / "case_studies"
RUNS_CSV = SUMMARY / "real_ablation_runs.csv"
METHODS = ["team", "no_research", "single_agent"]
FIELDS = [
    "project",
    "method",
    "verdict",
    "packages_kept",
    "packages_rolled_back",
    "packages_other",
    "lines_removed",
    "files_removed",
    "reviewed",
    "reviewer_accept",
    "reviewer_reject",
    "reviewer_unsure",
    "code_edits",
    "wrong",
    "debatable",
    "ui_check",
    "llm_requests",
    "prompt_tokens",
    "completion_tokens",
    "minutes",
]


def runs() -> list[Path]:
    """The ablation records that finished (they have a summary)."""
    return sorted(p for p in CASES.glob("*-abl-*") if (p / "summary.json").exists())


def review() -> None:
    from exp_llm_review import review_sheet
    from exp_review_sheet import write_sheet

    for run in runs():
        if not (run / "llm_review.json").exists():
            write_sheet(run.name, run.name, None)
            print(review_sheet(run.name, None, 0))


def ui() -> None:
    from cleansweep.core.config import load_config
    from cleansweep.core.io import load_json
    from cleansweep.core.models import SweepReport
    from cleansweep.guard import ui_check
    from cleansweep.sandbox import open_workspace

    mine = [r for r in runs() if r.name.startswith("shotgun-abl-")]
    if not mine:
        return
    sandbox = load_config()["core"]["sandbox"]
    target = json.loads((mine[0] / "report.json").read_text())["repo_id"]
    ws = open_workspace(target, sandbox)
    try:
        base = ui_check.baseline(ws, ui_check.textual_modules(ws.path))
    finally:
        ws.close()
    for run in mine:
        report = load_json(SweepReport, run / "report.json")
        kept = {r.item_id for r in report.results if r.status == "kept"}
        items = [i for i in report.plan.items if i.item_id in kept]
        ws = open_workspace(target, sandbox)
        try:
            diff = report.stats.get("final_diff", "")
            if diff.strip() and not ws.apply_patch(diff):
                result = {"ok": None, "error": "the final diff did not apply"}
            else:
                after = ui_check.snapshot(ws, base["modules"])
                result = ui_check.compare(base, after, ui_check.deleted_names(items))
        finally:
            ws.close()
        (run / "ui_check.json").write_text(json.dumps(result, indent=1) + "\n")
        print(run.name, {k: result.get(k) for k in ("ok", "changed", "lost", "broken")})


def _reviewer(run: Path) -> dict:
    path = run / "llm_review.json"
    if not path.exists():
        return {}
    kinds = {
        str(r["n"]): r["kind"] for r in json.loads((run / "review_rows.json").read_text())["rows"]
    }
    votes = [
        v["decision"]
        for n, v in json.loads(path.read_text())["reviews"].items()
        if kinds.get(n) == "applied"
    ]
    return {
        "reviewed": len(votes),
        **{f"reviewer_{d}": votes.count(d) for d in ("accept", "reject", "unsure")},
    }


def _audit() -> dict[str, dict]:
    """Per run: kept code edits, and those checked wrong or debatable."""
    import exp_diff_audit

    _, rows = exp_diff_audit.collect()
    verdicts = {e: c["verdict"] for e, c in exp_diff_audit.checks().items()}
    out: dict[str, dict] = {}
    for row in rows:
        if row["source"] != "real-project ablation":
            continue
        run = out.setdefault(row["run"], {"code_edits": 0, "wrong": 0, "debatable": 0})
        run["code_edits"] += 1
        verdict = verdicts.get(row["edit"])
        if verdict in ("wrong", "debatable"):
            run[verdict] += 1
    return out


def _ui_text(run: Path) -> str:
    path = run / "ui_check.json"
    if not path.exists():
        return ""
    result = json.loads(path.read_text())
    if result.get("ok") is None:
        return result.get("error", "not run")
    if result["ok"]:
        return f"ok ({result['classes']} classes, {len(result['removed'])} removed by the cleanup)"
    return "; ".join(f"{k} {len(result[k])}" for k in ("changed", "lost", "broken") if result[k])


def diff_counts(stats: dict) -> dict:
    """Lines removed (deleted minus added) and files deleted, from the run's final diff: the
    single agent's summary of a local project says 0, because it leaves no branch to count."""
    lines = stats.get("final_diff", "").splitlines()
    minus = sum(x.startswith("-") and not x.startswith("---") for x in lines)
    plus = sum(x.startswith("+") and not x.startswith("+++") for x in lines)
    files = sum(x.startswith("deleted file mode") for x in lines)
    return {"lines_removed": minus - plus, "files_removed": files}


def collect() -> Path:
    audit = _audit()
    rows = []
    for run in runs():
        project, _, method = run.name.partition("-abl-")
        s = json.loads((run / "summary.json").read_text())
        packages = s.get("packages") or {}
        rows.append(
            {
                "project": project,
                "method": method,
                "verdict": s["verdict"],
                "packages_kept": packages.get("kept", 0),
                "packages_rolled_back": packages.get("rolled_back", 0),
                "packages_other": sum(packages.values())
                - packages.get("kept", 0)
                - packages.get("rolled_back", 0),
                **diff_counts(json.loads((run / "report.json").read_text())["stats"]),
                **{
                    "reviewed": "",
                    "reviewer_accept": "",
                    "reviewer_reject": "",
                    "reviewer_unsure": "",
                },
                **_reviewer(run),
                **audit.get(run.name, {"code_edits": 0, "wrong": 0, "debatable": 0}),
                "ui_check": _ui_text(run),
                "llm_requests": s.get("llm_requests", 0),
                "prompt_tokens": s.get("prompt_tokens", 0),
                "completion_tokens": s.get("completion_tokens", 0),
                "minutes": round(s["seconds"] / 60, 1),
            }
        )
    RUNS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return RUNS_CSV


def _sum(rows: list[dict], key: str) -> int:
    return sum(int(r[key] or 0) for r in rows)


def method_table(rows: list[dict]) -> list[dict]:
    """Per method: verdicts, packages, the LLM reviewer's acceptance of kept changes, confirmed
    wrong edits, the UI check and cost."""
    out = []
    for method in METHODS:
        mine = [r for r in rows if r["method"] == method]
        if not mine:
            continue
        verdicts = sorted({r["verdict"] for r in mine})
        decided = _sum(mine, "reviewer_accept") + _sum(mine, "reviewer_reject")
        ui_rows = [r["ui_check"] for r in mine if r["ui_check"]]
        out.append(
            {
                "method": method,
                "projects": len(mine),
                "verdicts": "; ".join(
                    f"{v} {sum(r['verdict'] == v for r in mine)}" for v in verdicts
                ),
                "packages kept / rolled back": f"{_sum(mine, 'packages_kept')} / "
                f"{_sum(mine, 'packages_rolled_back')}",
                "lines removed": _sum(mine, "lines_removed"),
                "LLM reviewer accepts kept changes (LLM-judged)": f"{_sum(mine, 'reviewer_accept')}"
                f"/{decided} ({_sum(mine, 'reviewer_unsure')} unsure)",
                "confirmed wrong / debatable of kept code edits (LLM-judged reading)": (
                    f"{_sum(mine, 'wrong')} / {_sum(mine, 'debatable')} of "
                    f"{_sum(mine, 'code_edits')}"
                ),
                "UI check (shotgun)": ui_rows[0] if ui_rows else "",
                "LLM requests (mean)": round(_sum(mine, "llm_requests") / len(mine), 1),
                "minutes (mean)": round(sum(float(r["minutes"]) for r in mine) / len(mine), 1),
            }
        )
    return out


def table() -> Path | None:
    if not RUNS_CSV.exists():
        return None
    with RUNS_CSV.open() as f:
        rows = list(csv.DictReader(f))
    out = method_table(rows)
    path = SUMMARY / "real_ablation.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    cols = list(out[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in out]
    (SUMMARY / "real_ablation.md").write_text("\n".join(lines) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["review", "ui", "collect", "table"])
    args = parser.parse_args(argv)
    if args.what == "review":
        review()
    elif args.what == "ui":
        from cleansweep.sandbox.scratch import on_start

        on_start()
        ui()
    elif args.what == "collect":
        print(collect())
    else:
        print(table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
