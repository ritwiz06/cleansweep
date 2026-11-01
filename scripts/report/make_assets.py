"""Rebuild the progress-report tables and charts from results/raw/.

Run from the repo root:  python scripts/report/make_assets.py
Writes results/summary/v1/*.md and *.csv, results/figures/v1/*.png, and renders
scripts/report/pipeline.mmd to results/figures/v1/pipeline.png when mermaid-cli (mmdc) is installed.
results/raw/ is not in git, so only a machine with the runs can regenerate these.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.dashboard.live_runner import fold, list_runs, read_events  # noqa: E402
from app.dashboard.loaders import compare_reports, load_report, outcome_score  # noqa: E402

RAW = ROOT / "results" / "raw"
HERE = Path(__file__).resolve().parent
TABLES = ROOT / "results" / "summary" / "v1"
FIGURES = ROOT / "results" / "figures" / "v1"
TOY_KEY = ROOT / "tests" / "fixtures" / "toy_repo_expected.json"
DEMO_KEY = ROOT / "demo" / "shop_app_expected.json"

# The toy runs that make up the methods table (2026-10-24, judge qwen36-27b, prompt v2).
TOY_RUNS = {
    "judge_off": "cleansweep, judge off",
    "judge_gatekeeper": "cleansweep, gatekeeper",
    "judge_advisory": "cleansweep, advisory",
    "tools_only": "tools_only",
    "no_batching": "no_batching, gatekeeper",
}
MODELS = ["qwen36-35b-a3b", "kimi-k2-7-code", "qwen36-27b"]

# Chart tokens (light mode; validated with the dataviz palette checker).
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
SERIES = {"toy repo": "#2a78d6", "demo app": "#eb6834"}


def write_table(df: pd.DataFrame, name: str) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    df.to_csv(TABLES / f"{name}.csv", index=False)
    cells = [[str(v) for v in df.columns]] + [
        ["" if pd.isna(v) else str(v) for v in row] for row in df.itertuples(index=False)
    ]
    lines = ["| " + " | ".join(cells[0]) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(row) + " |" for row in cells[1:]]
    (TABLES / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def toy_methods() -> pd.DataFrame:
    runs = compare_reports(RAW / "toy").set_index("run")
    rows = []
    for run, label in TOY_RUNS.items():
        r = runs.loc[run]
        rows.append(
            {
                "run": label,
                "kept": int(r["kept"]),
                "test runs": int(r["test runs"]),
                "lines removed": int(r["lines removed"]),
                "visible broken": int(r["visible broken"]),
                "hidden changed": "yes" if r["hidden changed"] else "no",
            }
        )
    return pd.DataFrame(rows)


def replay_recordings() -> pd.DataFrame:
    rows = []
    for run_dir in sorted(list_runs(RAW / "live"), key=lambda p: p.name):
        state = fold(read_events(run_dir / "events.jsonl"))
        run, report = state["run"], load_report(run_dir / "report.json")
        target = Path(run["target"])
        target = target if target.is_absolute() else ROOT / target
        key = Path(str(target).rstrip("/") + "_expected.json")
        score = outcome_score(report, key) if key.exists() else None
        rows.append(
            {
                "recording": run_dir.name,
                "target": "toy repo" if "toy_repo" in str(target) else "demo app + feature",
                "method": run.get("method", "cleansweep"),
                "judge mode": run["judge_mode"],
                "model": run.get("model"),
                "kept": report.stats["items_kept"] + report.stats["items_repaired"],
                "test runs": report.stats["test_runs"],
                "lines removed": report.stats["lines_removed"],
                "hidden changed": "yes"
                if (state["hidden"] or {}).get("behavior_changed")
                else "no",
                "outcome": f"{score['hits']}/{score['total']}" if score else "",
            }
        )
    return pd.DataFrame(rows)


# Part A of S16: the same targets with the Guard's differential probes (2026-10-26).
PROBE_RUNS = [
    "20261026_toy_advisory_probes",
    "20261026_toy_gatekeeper_probes",
    "20261026_toy_guard_tests_only",
    "20261026_demo_feature_advisory_probes",
    "20261026_demo_feature_gatekeeper_probes",
]


def probe_runs() -> pd.DataFrame:
    """What the probes caught, and what they wrongly blocked, per recorded run."""
    rows = []
    for name in PROBE_RUNS:
        run_dir = RAW / "live" / name
        if not (run_dir / "report.json").exists():
            continue
        state = fold(read_events(run_dir / "events.jsonl"))
        run, report = state["run"], load_report(run_dir / "report.json")
        target = Path(run["target"])
        target = target if target.is_absolute() else ROOT / target
        score = outcome_score(report, Path(str(target).rstrip("/") + "_expected.json"))
        expected = {row["unit"]: row["expected"] for _, row in score["table"].iterrows()}
        units = {i.item_id: i.unit.key for i in report.plan.items}
        by_probes = [
            r for r in report.results if r.status == "rolled_back" and r.notes.startswith("probes")
        ]
        false_alarms = [r for r in by_probes if expected.get(units[r.item_id]) == "applied"]
        rows.append(
            {
                "target": "toy repo" if "toy_repo" in str(target) else "demo app + feature",
                "method": run.get("method", "cleansweep"),
                "judge mode": run["judge_mode"],
                "kept": report.stats["items_kept"] + report.stats["items_repaired"],
                "rolled back by probes": len(by_probes),
                "false alarms": len(false_alarms),
                "test runs": report.stats["test_runs"],
                "hidden changed": "yes"
                if (state["hidden"] or {}).get("behavior_changed")
                else "no",
                "outcome": f"{score['hits']}/{score['total']}",
            }
        )
    return pd.DataFrame(rows)


T1 = RAW / "swebench_t1"
T1_METHODS = [
    "cleansweep-gatekeeper",
    "cleansweep-advisory",
    "guard_tests_only",
    "tools_only",
    "one_shot_llm",
]


def _t1_reports(label: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(T1.glob(f"*__{label}.json"))]


def swebench_tier1() -> pd.DataFrame:
    """One row per method over the Tier 1 patches (results/raw/swebench_t1/)."""
    rows = []
    for label in T1_METHODS:
        reports = _t1_reports(label)
        if not reports:
            continue
        found: dict[str, int] = {}
        rolled = {"tests": 0, "probes": 0, "other": 0}
        for r in reports:
            for item in r["plan"]["items"]:
                found[item["category"]] = found.get(item["category"], 0) + 1
            for res in r["results"]:
                if res["status"] == "rolled_back":
                    check = res["notes"].split(" failed:", 1)[0]
                    rolled[check if check in rolled else "other"] += 1
        stats = [r["stats"] for r in reports]
        rows.append(
            {
                "method": label,
                "patches": len(reports),
                "items found": ", ".join(
                    f"{k} {v}" for k, v in sorted(found.items(), key=lambda kv: -kv[1])
                ),
                "edits applied": sum(
                    res["status"] in ("kept", "repaired") and bool(res["diff"].strip())
                    for r in reports
                    for res in r["results"]
                ),
                "files removed": sum(s["files_removed"] for s in stats),
                "rolled back (tests / probes / other)": (
                    f"{rolled['tests']} / {rolled['probes']} / {rolled['other']}"
                ),
                "lines removed": sum(s["lines_removed"] for s in stats),
                "test runs": sum(s["test_runs"] for s in stats),
                "hidden changed": f"{sum(bool(s['hidden'].get('behavior_changed')) for s in stats)}"
                f"/{len(stats)}",
                "LLM calls": sum(s["llm_calls"] for s in stats),
                "min per patch": round(sum(s["minutes"] for s in stats) / len(stats), 1),
                "invalid output": sum(int(s.get("invalid_output", 0)) for s in stats),
            }
        )
    return pd.DataFrame(rows)


def swebench_tier1_patches() -> pd.DataFrame:
    """One row per Tier 1 patch: what CleanSweep (advisory) found and kept, per method."""
    splits = json.loads((ROOT / "data" / "splits" / "swebench_tier1.json").read_text())
    rows = []
    for entry in splits:
        row = {
            "instance": entry["instance_id"],
            "agent": entry["agent"],
            "differs from oracle": "yes" if entry["differs_from_oracle"] else "no",
        }
        for label in T1_METHODS:
            path = T1 / f"{entry['instance_id']}__{entry['agent']}__{label}.json"
            if not path.exists():
                row[label] = ""
                continue
            report = json.loads(path.read_text())
            applied = sum(
                res["status"] in ("kept", "repaired") and bool(res["diff"].strip())
                for res in report["results"]
            )
            changed = report["stats"]["hidden"].get("behavior_changed")
            row[label] = f"{applied} applied" + (", hidden changed" if changed else "")
        rows.append(row)
    return pd.DataFrame(rows)


def slop_kinds() -> pd.DataFrame:
    """What the agent patches left behind: every item the Reviewer found (advisory runs)."""
    kinds: dict[str, dict] = {}
    for r in _t1_reports("cleansweep-advisory"):
        patch = r["repo_id"].split(":", 1)[1]
        for item in r["plan"]["items"]:
            kind = item["category"]
            if kind == "leftover_file":
                agent_made = any("added by the agent patch" in e for e in item["evidence"])
                kind += " (scratch outside the project)" if agent_made else " (name pattern)"
            row = kinds.setdefault(
                kind, {"kind": kind, "items": 0, "patches": set(), "examples": []}
            )
            row["items"] += 1
            row["patches"].add(patch)
            if len(row["examples"]) < 3:
                row["examples"].append(
                    item["unit"]["path"]
                    + (f"::{item['unit']['name']}" if item["unit"].get("name") else "")
                )
    out = [
        {**row, "patches": len(row["patches"]), "examples": ", ".join(row["examples"])}
        for row in sorted(kinds.values(), key=lambda r: -r["items"])
    ]
    return pd.DataFrame(out, columns=["kind", "items", "patches", "examples"])


def _lane_hits(report, key_path: Path) -> tuple[int, int, bool]:
    key = json.loads(key_path.read_text())["items"]
    lanes = {i.unit.key: i.lane for i in report.plan.items}
    trap = next(r["key"] for r in key if r.get("trap") == "near_duplicate")
    hits = sum(lanes.get(r["key"]) == r["expected_lane"] for r in key)
    return hits, len(key), lanes.get(trap) != "safe"


def judge_runs() -> pd.DataFrame:
    """One row per judge-check run on either answer key."""
    sources = [
        ("toy repo", RAW / "judge_check", TOY_KEY, "{m}__s*.json"),
        ("demo app", RAW / "demo_check", DEMO_KEY, "{m}.json"),
    ]
    rows = []
    for target, folder, key, pattern in sources:
        for model in MODELS:
            for path in sorted(folder.glob(pattern.format(m=model))):
                if path.name.endswith(".extra.json"):
                    continue
                report = load_report(path)
                extra = json.loads(path.with_suffix(".extra.json").read_text())
                lane, total, trap_out = _lane_hits(report, key)
                score = outcome_score(report, key)
                calls = [c["seconds"] for c in extra["calls"]]
                rows.append(
                    {
                        "answer key": target,
                        "model": model,
                        "run": path.stem,
                        "lane hits": lane,
                        "outcome hits": score["hits"],
                        "items": total,
                        "trap kept out": trap_out,
                        "hidden changed": bool(extra["hidden"].get("behavior_changed")),
                        "s per request": round(sum(calls) / len(calls), 1) if calls else None,
                    }
                )
    return pd.DataFrame(rows)


def judge_summary(runs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (target, model), g in runs.groupby(["answer key", "model"], sort=False):
        items = int(g["items"].iloc[0])
        rows.append(
            {
                "answer key": target,
                "model": model,
                "runs": len(g),
                "lane accuracy": f"{g['lane hits'].mean() / items:.1%}",
                "outcome accuracy": f"{g['outcome hits'].mean() / items:.1%}",
                "trap kept out": f"{int(g['trap kept out'].sum())}/{len(g)}",
                "hidden changed": f"{int(g['hidden changed'].sum())}/{len(g)}",
                "s per request (mean)": round(g["s per request"].mean(), 1),
            }
        )
    return pd.DataFrame(rows)


def _style(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8.5, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def chart_toy_methods(df: pd.DataFrame) -> None:
    labels = list(df["run"])[::-1]
    data = df.iloc[::-1]
    fig, axes = plt.subplots(
        1, 2, figsize=(9, 3.2), dpi=200, sharey=True, gridspec_kw={"wspace": 0.08}
    )
    fig.patch.set_facecolor(SURFACE)
    for ax, column, title in ((axes[0], "kept", "Edits kept"), (axes[1], "test runs", "Test runs")):
        values = list(data[column])
        ax.barh(
            labels, values, height=0.55, color=SERIES["toy repo"], edgecolor=SURFACE, linewidth=2
        )
        for y, v in enumerate(values):
            ax.text(v + max(values) * 0.02, y, str(v), va="center", fontsize=8.5, color=INK)
        ax.set_xlim(0, max(values) * 1.18)
        _style(ax, title)
    axes[0].tick_params(axis="y", colors=INK, labelsize=9)
    for y, changed in enumerate(data["hidden changed"]):
        mark = "✗ hidden checks changed" if changed == "yes" else "✓ hidden checks unchanged"
        axes[1].text(
            1.04,
            y,
            mark,
            transform=axes[1].get_yaxis_transform(),
            va="center",
            fontsize=8.5,
            color=INK if changed == "yes" else INK_2,
            fontweight="bold" if changed == "yes" else "normal",
        )
    fig.suptitle(
        "Toy repo: methods compared (judge qwen36-27b, 2026-10-24)",
        x=0.01,
        ha="left",
        fontsize=11,
        color=INK,
        y=1.02,
    )
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "toy_methods.png", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def chart_judge_models(runs: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), dpi=200, gridspec_kw={"wspace": 0.35})
    fig.patch.set_facecolor(SURFACE)
    height = 0.36
    for n, (target, color) in enumerate(SERIES.items()):
        g = runs[runs["answer key"] == target]
        for m, model in enumerate(MODELS):
            y = len(MODELS) - 1 - m + (height / 2 if n == 0 else -height / 2)
            rows = g[g["model"] == model]
            if rows.empty:
                for ax in axes:
                    ax.text(
                        0.01,
                        y,
                        "not run",
                        transform=ax.get_yaxis_transform(),
                        va="center",
                        fontsize=8,
                        color=INK_2,
                        style="italic",
                    )
                continue
            accuracy = 100 * rows["outcome hits"].mean() / rows["items"].iloc[0]
            axes[0].barh(
                y,
                accuracy,
                height=height,
                color=color,
                edgecolor=SURFACE,
                linewidth=2,
                label=target if m == 0 else None,
            )
            axes[0].text(accuracy + 2, y, f"{accuracy:.0f}%", va="center", fontsize=8, color=INK)
            seconds = rows["s per request"]
            axes[1].barh(
                y, seconds.mean(), height=height, color=color, edgecolor=SURFACE, linewidth=2
            )
            axes[1].scatter(
                seconds,
                [y] * len(seconds),
                s=14,
                color=INK,
                zorder=3,
                edgecolors=SURFACE,
                linewidths=1,
            )
            # the label says "mean", so it can sit past the slowest run without being misread
            mean = seconds.mean()
            label_x = max(mean, seconds.max()) + 6
            axes[1].text(label_x, y, f"mean {mean:.0f} s", va="center", fontsize=8, color=INK)
    for ax, title in (
        (axes[0], "Outcome accuracy vs. answer key"),
        (axes[1], "Seconds per judge request (bar = mean, dots = runs)"),
    ):
        ax.set_yticks(range(len(MODELS)), MODELS[::-1])
        _style(ax, title)
        ax.tick_params(axis="y", colors=INK, labelsize=9)
    axes[0].set_xlim(0, 118)
    axes[0].xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    axes[1].set_xlim(0, runs["s per request"].max() * 1.25)
    axes[0].legend(
        loc="lower left",
        bbox_to_anchor=(0, -0.2),
        ncol=2,
        frameon=False,
        fontsize=8.5,
        labelcolor=INK,
    )
    fig.suptitle(
        "Judge models on both answer keys (gatekeeper mode)",
        x=0.01,
        ha="left",
        fontsize=11,
        color=INK,
        y=1.02,
    )
    fig.savefig(FIGURES / "judge_models.png", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


OPEN_FAILED = "open failed: CalledProcessError"


def chart_aidev_funnel() -> None:
    """AIDev selection: repositories left after each step (log scale), drop reasons below."""
    path = ROOT / "results" / "data_summary" / "aidev_funnel.csv"
    if not path.exists():
        return
    funnel = pd.read_csv(path)
    stages = funnel[~funnel["stage"].str.startswith("dropped")].iloc[::-1]
    drops = funnel[funnel["stage"].str.startswith("dropped")]
    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    names = {"in committed files": "used here (1 excluded)"}
    labels, values = [names.get(s, s) for s in stages["stage"]], list(stages["count"])
    ax.barh(labels, values, height=0.55, color=SERIES["toy repo"], edgecolor=SURFACE, linewidth=2)
    for y, v in enumerate(values):
        ax.text(v * 1.15, y, f"{v:,}", va="center", fontsize=8.5, color=INK)
    ax.set_xscale("log")
    ax.set_xlim(10, max(values) * 4)
    _style(ax, "AIDev repositories kept at each step (log scale)")
    ax.tick_params(axis="y", colors=INK, labelsize=8.5)
    reasons = ", ".join(
        f"{s.removeprefix('dropped: ').replace(OPEN_FAILED, 'could not be opened')} {c}"
        for s, c in zip(drops["stage"], drops["count"], strict=True)
    )
    ax.set_xlabel(f"Dropped of 120: {reasons}", fontsize=7.5, color=INK_2)
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "aidev_funnel.png", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def render_pipeline() -> str:
    mmdc = shutil.which("mmdc")
    if mmdc is None:
        return "pipeline.png not rendered (mermaid-cli not installed)"
    subprocess.run(
        [
            mmdc,
            "-i",
            str(HERE / "pipeline.mmd"),
            "-o",
            str(FIGURES / "pipeline.png"),
            "-b",
            "white",
        ],
        check=True,
        capture_output=True,
    )
    return "pipeline.png rendered"


def main() -> None:
    toy = toy_methods()
    write_table(toy, "toy_methods")
    write_table(replay_recordings(), "replay_recordings")
    write_table(probe_runs(), "probe_runs")
    if T1.exists():
        write_table(swebench_tier1(), "swebench_tier1")
        write_table(swebench_tier1_patches(), "swebench_tier1_patches")
        write_table(slop_kinds(), "swebench_tier1_slop")
    runs = judge_runs()
    write_table(judge_summary(runs), "judge_checks")
    write_table(runs, "judge_check_runs")
    chart_toy_methods(toy)
    chart_judge_models(runs)
    chart_aidev_funnel()
    print(render_pipeline())
    for path in sorted([*TABLES.iterdir(), *FIGURES.iterdir()]):
        if path.is_file() and path.suffix in (".md", ".csv", ".png", ".mmd"):
            print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
