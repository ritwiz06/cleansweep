"""The v3 figures, from the v3 tables only (results/summary/v3/), in one style.

    python scripts/report/make_figures_v3.py

Writes to results/figures/v3/: safety_yield.png (REAL: wrong kept code edits in two tiers against
lines removed), injection_recall.png (INJECT recall with bootstrap intervals), audit_tiers.png
(wrong edits per method and set, confirmed and reading), heldout.png (REAL projects with a
held-out change or a visible break), autonomy.png (the failure taxonomy per pass) and cost.png
(LLM requests per run). A figure whose table does not exist yet is skipped.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "results" / "summary" / "v3"
FIGURES = ROOT / "results" / "figures" / "v3"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
# one color per method, in a fixed order (Okabe-Ito hues; v1 in gray)
COLORS = {
    "agentic": "#0072B2",
    "agentic-no_resolver": "#56B4E9",
    "agentic-batch": "#009E73",
    "agentic-no_research": "#CC79A7",
    "agentic-single_agent": "#E69F00",
    "aider": "#D55E00",
    "cleansweep": "#7a7974",
    "agentic-thorough": "#2b4f7a",
    "agentic-adaptive": "#8a6a00",
}
NAMES = {
    "agentic": "team",
    "agentic-no_resolver": "team, resolver off",
    "agentic-batch": "team, batching",
    "agentic-no_research": "no research squad",
    "agentic-single_agent": "single agent",
    "aider": "Aider",
    "cleansweep": "v1",
    "agentic-thorough": "team, thorough",
    "agentic-adaptive": "team, adaptive",
}


def rows(name: str) -> list[dict]:
    path = SUMMARY / name
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def axes(n: int = 1, width: float = 7.0, height: float = 3.0):
    plt.rcParams.update({"font.size": 9, "font.family": "DejaVu Sans"})
    fig, axs = plt.subplots(1, n, figsize=(width, height), dpi=200, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax in axs[0]:
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(GRID)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK_2, length=0)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    return fig, list(axs[0])


def save(fig, name: str) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def hbars(ax, labels: list[str], values: list[float], colors: list[str], title: str) -> None:
    y = range(len(labels))
    ax.barh(list(y), values, height=0.6, color=colors, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(list(y), labels, color=INK)
    ax.invert_yaxis()
    ax.set_title(title, loc="left", color=INK, fontsize=9.5)


def safety_yield() -> Path | None:
    # a method with no finished run on the curve's projects has no point to place
    data = [r for r in rows("curve.csv") if r["method"] in COLORS and r.get("finished", "1") != "0"]
    if not data:
        return None
    fig, (ax,) = axes(height=3.4)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    for r in data:
        x, color = num(r["lines_removed"]), COLORS[r["method"]]
        wrong = num(r["wrong_all_tiers (incl. LLM-judged readings)"])
        confirmed = num(r["wrong_confirmed"])
        ax.scatter([x], [wrong], s=48, color=color, edgecolor=SURFACE, linewidth=1.5, zorder=3)
        ax.scatter([x], [confirmed], s=48, facecolor=SURFACE, edgecolor=color, linewidth=1.5)
        ax.annotate(
            NAMES[r["method"]],
            (x, wrong),
            xytext=(5, 3),
            textcoords="offset points",
            fontsize=8,
            color=INK,
        )
    ax.set_xlabel("lines removed (the first five REAL projects, finished runs)", color=INK_2)
    ax.set_ylabel("wrong kept code edits", color=INK_2)
    ax.set_title(
        "Safety against yield: filled = all tiers (incl. LLM-judged), open = confirmed",
        loc="left",
        color=INK,
        fontsize=9.5,
    )
    return save(fig, "safety_yield.png")


def injection_recall() -> Path | None:
    data = [r for r in rows("injection.csv") if r["method"] in COLORS and r["recall"] != ""]
    if not data:
        return None
    fig, (ax,) = axes(height=0.45 * len(data) + 1)
    labels = [NAMES[r["method"]] for r in data]
    values = [num(r["recall"]) for r in data]
    hbars(
        ax,
        labels,
        values,
        [COLORS[r["method"]] for r in data],
        "INJECT seed 4 (out of sample): planted slop removed, 95% interval over repositories",
    )
    for y, r in enumerate(data):
        low, high = num(r["recall_ci_low"]), num(r["recall_ci_high"])
        ax.plot([low, high], [y, y], color=INK, linewidth=1)
        ax.text(high + 0.02, y, f"{num(r['recall']):.2f}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, 1.1)
    return save(fig, "injection_recall.png")


def audit_tiers() -> Path | None:
    data = [
        r for r in rows("audit.csv") if r["method"] in COLORS and int(r["kept_code_edits"] or 0)
    ]
    if not data:
        return None
    sets = [s for s in ("injected v3", "real v3") if any(r["set"] == s for r in data)]
    order = [m for m in COLORS if any(r["method"] == m for r in data)]  # one order, both panels
    fig, axs = axes(len(sets), height=0.45 * len(order) + 1.2)
    fig.subplots_adjust(wspace=0.12)
    y = list(range(len(order)))
    for n, (ax, s) in enumerate(zip(axs, sets, strict=True)):
        mine = {r["method"]: r for r in data if r["set"] == s}
        confirmed = [num(mine[m]["share_confirmed"]) if m in mine else 0.0 for m in order]
        total = [num(mine[m]["share_all_tiers"]) if m in mine else 0.0 for m in order]
        colors = [COLORS[m] for m in order]
        ax.barh(y, confirmed, height=0.6, color=colors, edgecolor=SURFACE, linewidth=2)
        reading = [t - c for t, c in zip(total, confirmed, strict=True)]
        ax.barh(
            y,
            reading,
            left=confirmed,
            height=0.6,
            color=colors,
            alpha=0.35,
            edgecolor=SURFACE,
            linewidth=2,
            hatch="///",
        )
        ax.set_yticks(y, [NAMES[m] for m in order] if n == 0 else [""] * len(order), color=INK)
        ax.invert_yaxis()
        for yy, m in zip(y, order, strict=True):
            if m in mine:
                ax.text(
                    num(mine[m]["share_all_tiers"]) + 0.002,
                    yy,
                    f"n={mine[m]['kept_code_edits']}",
                    va="center",
                    fontsize=7.5,
                    color=INK_2,
                )
        title = {"injected v3": "INJECT", "real v3": "REAL"}[s]
        ax.set_title(
            f"{title}: wrong share of kept code edits", loc="left", color=INK, fontsize=9.5
        )
    axs[0].set_xlabel("solid = confirmed, hatched = reading (LLM-judged)", color=INK_2)
    return save(fig, "audit_tiers.png")


def heldout() -> Path | None:
    data = [r for r in rows("real.csv") if r["method"] in COLORS]
    if not data:
        return None
    fig, (ax,) = axes(height=0.45 * len(data) + 1)
    labels = [f"{NAMES[r['method']]} ({r['finished']} finished)" for r in data]
    values = [num(r["heldout_changed_projects (finished)"]) for r in data]
    hbars(
        ax,
        labels,
        values,
        [COLORS[r["method"]] for r in data],
        "REAL: projects where a held-out test stopped passing",
    )
    for y, r in enumerate(data):
        broken = r["visible_broken_projects (finished)"]
        ax.text(
            num(r["heldout_changed_projects (finished)"]) + 0.05,
            y,
            f"{r['heldout_changed_projects (finished)']} (visible broken: {broken})",
            va="center",
            fontsize=8,
            color=INK,
        )
    ax.set_xlim(0, max([*values, 1]) + 1)  # counts: never a negative axis, room for the labels
    ax.xaxis.get_major_locator().set_params(integer=True)
    return save(fig, "heldout.png")


def autonomy() -> Path | None:
    data = rows("autonomy_runs.csv")
    failed = [r for r in data if r.get("completed") != "True"]
    if not data:
        return None
    classes = sorted({(r.get("environment") or r.get("failure") or "other") for r in failed})
    fig, axs = axes(1, height=0.4 * max(len(classes), 1) + 1.2)
    ax = axs[0]
    passes = sorted({r["pass"] for r in data})
    colors = ["#0072B2", "#E69F00"]
    for k, (p, color) in enumerate(zip(passes, colors, strict=False)):
        counts = [
            sum(
                (r.get("environment") or r.get("failure") or "other") == c
                for r in failed
                if r["pass"] == p
            )
            for c in classes
        ]
        ax.barh(
            [i + 0.38 * k for i in range(len(classes))],
            counts,
            height=0.36,
            color=color,
            label=f"pass {p}",
        )
    ax.set_yticks([i + 0.19 for i in range(len(classes))], classes, color=INK)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(
        "AUTONOMY: runs that did not complete, by cause", loc="left", color=INK, fontsize=9.5
    )
    return save(fig, "autonomy.png")


def cost() -> Path | None:
    data = [r for r in rows("cost.csv") if r["method"] in COLORS and r["llm_requests_mean"] != ""]
    if not data:
        return None
    sets = sorted({r["set"] for r in data})
    order = [m for m in COLORS if any(r["method"] == m for r in data)]  # one order, both panels
    fig, axs = axes(len(sets), height=0.45 * len(order) + 1)
    fig.subplots_adjust(wspace=0.12)
    for n, (ax, s) in enumerate(zip(axs, sets, strict=True)):
        mine = {r["method"]: num(r["llm_requests_mean"]) for r in data if r["set"] == s}
        hbars(
            ax,
            [NAMES[m] if n == 0 else "" for m in order],
            [mine.get(m, 0.0) for m in order],
            [COLORS[m] for m in order],
            f"{s}: LLM requests per finished run",
        )
    return save(fig, "cost.png")


def main() -> int:
    for make in (safety_yield, injection_recall, audit_tiers, heldout, autonomy, cost):
        path = make()
        print(path if path else f"{make.__name__}: no table yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
