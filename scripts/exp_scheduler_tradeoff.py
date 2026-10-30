"""Scheduler trade-off: what each sweep policy costs in test runs and buys in slop debt.

    python scripts/exp_scheduler_tradeoff.py

Reads results/summary/scheduler_replay.csv (exp_replay.py). Per repository, the slop-debt
reduction of a policy is 1 - its slop debt / the debt of never sweeping. Per policy: mean and
95% bootstrap CI across repositories for the reduction and the estimated test runs, plus the mean
resurrection rate. Writes results/summary/scheduler_tradeoff.csv and
results/figures/scheduler_tradeoff.png.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.eval.stats import bootstrap_ci  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("CLEANSWEEP_RESULTS", ROOT / "results"))
REPLAY = RESULTS / "summary" / "scheduler_replay.csv"
OUT = RESULTS / "summary" / "scheduler_tradeoff.csv"
FIGURE = RESULTS / "figures" / "scheduler_tradeoff.png"
POLICIES = ["every_pr", "every_n", "daily", "adaptive"]
NAMES = {
    "every_pr": "after every agent PR",
    "every_n": "every 5 commits",
    "daily": "daily",
    "adaptive": "adaptive (2%)",
}
# label placement (points from the marker, alignment); the low-cost points sit close together
OFFSETS = {"adaptive": (0, -12, "center")}
# chart tokens, as in docs/report/make_assets.py
SURFACE, INK, INK_2, GRID, MARK = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#2a78d6"


def repos_label(repos: int) -> str:
    """ "20 of 21 runnable repos (1 excluded)" when runnable repos were left out (DECISIONS)."""
    excluded = int(load_config()["data"]["aidev"].get("excluded_runnable", 0))
    if not excluded:
        return f"{repos} runnable AIDev repos"
    return f"{repos} of {repos + excluded} runnable AIDev repos ({excluded} excluded)"


def tradeoff(replay: pd.DataFrame) -> pd.DataFrame:
    none = replay[replay.policy == "none"].set_index("repo").slop_debt
    rows = []
    for policy in POLICIES:
        part = replay[replay.policy == policy].set_index("repo")
        base = none.reindex(part.index)
        keep = base > 0  # a repository with no slop at all has nothing to reduce
        reduction = (1 - part.slop_debt[keep] / base[keep]).tolist()
        runs = part.test_runs_est.astype(float).tolist()
        r_mean, r_lo, r_hi = bootstrap_ci(reduction)
        t_mean, t_lo, t_hi = bootstrap_ci(runs)
        rows.append(
            {
                "policy": policy,
                "repos": len(part),
                "repo_set": repos_label(len(part)),
                "debt_reduction_mean": round(r_mean, 3),
                "debt_reduction_lo": round(r_lo, 3),
                "debt_reduction_hi": round(r_hi, 3),
                "test_runs_mean": round(t_mean, 1),
                "test_runs_lo": round(t_lo, 1),
                "test_runs_hi": round(t_hi, 1),
                "sweeps_mean": round(part.sweeps.mean(), 2),
                "resurrection_rate_mean": round(part.resurrection_rate.mean(), 3),
            }
        )
    return pd.DataFrame(rows)


def figure(table: pd.DataFrame, repos: int) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 3.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for r in table.itertuples():
        ax.errorbar(
            r.test_runs_mean,
            r.debt_reduction_mean,
            xerr=[[r.test_runs_mean - r.test_runs_lo], [r.test_runs_hi - r.test_runs_mean]],
            yerr=[
                [r.debt_reduction_mean - r.debt_reduction_lo],
                [r.debt_reduction_hi - r.debt_reduction_mean],
            ],
            fmt="o",
            ms=8,
            color=MARK,
            ecolor=INK_2,
            elinewidth=1,
            capsize=0,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
        )
        ax.annotate(
            f"{NAMES[r.policy]}\nresurrection {r.resurrection_rate_mean:.2f}",
            (r.test_runs_mean, r.debt_reduction_mean),
            xytext=OFFSETS.get(r.policy, (8, -4))[:2],
            textcoords="offset points",
            fontsize=7.5,
            color=INK,
            va="top",
            ha=OFFSETS.get(r.policy, (0, 0, "left"))[2],
            bbox={"boxstyle": "square,pad=0.15", "fc": SURFACE, "ec": "none", "alpha": 0.9},
            zorder=3,
        )
    ax.set_xlabel("test runs per repository (mean, 95% CI)", fontsize=8, color=INK_2)
    ax.set_ylabel("slop-debt reduction vs. never sweeping", fontsize=8, color=INK_2)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlim(0, max(table.test_runs_hi) * 1.35)
    ax.set_ylim(0, 1.05)
    ax.set_title(f"Sweep policies on {repos_label(repos)}", loc="left", fontsize=10, color=INK)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=200)
    plt.close(fig)


def main() -> int:
    replay = pd.read_csv(REPLAY)
    table = tradeoff(replay)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    figure(table, replay.repo.nunique())
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
