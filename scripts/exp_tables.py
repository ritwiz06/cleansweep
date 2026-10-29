"""Main table (mean and 95% CI per method), paired tests, ablations and figures.

    python scripts/exp_tables.py

Reads results/summary/main_results.csv (from exp_collect.py) and guard_strength.csv. Writes
results/summary/{main_table,paired_tests,ablation}.{csv,md} and results/figures/*.png.
Toy and demo are one target each, so they are pooled as "answer keys" for intervals and tests.
Hidden changes marked flaky or overload_suspect (see exp_collect) count as no outcome. On AIDev,
where format edits can add more lines than they remove, the yield is lines_removed_code (lines
removed by edits other than format and unused imports) in the paired tests, ablation and figures.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from cleansweep.eval.stats import bootstrap_ci, mcnemar, wilcoxon  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary"
FIGURES = ROOT / "results" / "figures"
REFERENCE = "cleansweep-gatekeeper"
METHOD_ORDER = [
    "cleansweep-gatekeeper",
    "cleansweep-advisory",
    "guard_tests_only",
    "tools_only",
    "one_shot_llm",
    "one_shot_compile",
    "one_shot_retry",
]
SET_ORDER = ["answer keys", "swebench_t1", "swebench_t2", "aidev"]
# scatter marks: the three CleanSweep variants share a colour and differ by shape, and so do the
# three one-shot variants (a scatter keeps colours apart only up to three)
MARKS = {
    "cleansweep-gatekeeper": ("CleanSweep, gatekeeper", "#2a78d6", "o"),
    "cleansweep-advisory": ("CleanSweep, advisory", "#2a78d6", "s"),
    "guard_tests_only": ("tests-only Guard", "#2a78d6", "^"),
    "tools_only": ("tools only", "#eb6834", "D"),
    "one_shot_llm": ("one-shot LLM", "#1baf7a", "v"),
    "one_shot_compile": ("one-shot + compile check", "#1baf7a", "<"),
    "one_shot_retry": ("one-shot + retry", "#1baf7a", ">"),
}
METRICS = [
    ("lines_removed", "lines removed"),
    ("lines_removed_code", "lines removed excl. format/imports"),
    ("edits_applied", "edits"),
    ("hidden_changed", "hidden changed"),
]
# the yield measure per target set (lines_removed elsewhere)
YIELD = {"aidev": "lines_removed_code"}
YIELD_LABEL = {
    "lines_removed": "lines removed per target",
    "lines_removed_code": "lines removed excl. format/imports",
}
# chart tokens, as in docs/report/make_assets.py
SURFACE, INK, INK_2, GRID, BAR = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#2a78d6"


def read(path: Path) -> list[dict]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r.get("target_set") in ("toy", "demo"):
            r["target_set"] = "answer keys"
        for k in (
            "edits_applied",
            "lines_removed",
            "files_removed",
            "test_runs",
            "hidden_changed",
            "llm_calls",
            "invalid_output",
            "hidden_flaky",
            "format_edits",
            "import_edits",
            "lines_removed_code",
            "overload_suspect",
        ):
            if k in r and r[k] != "":
                r[k] = int(float(r[k]))
        if r.get("minutes"):
            r["minutes"] = float(r["minutes"])
        if r.get("hidden_flaky") == 1 or r.get("overload_suspect") == 1:
            # a flaky hidden test or an overloaded machine, not the edit (see exp_collect)
            r["hidden_changed"] = ""
    return rows


def yield_key(target_set: str) -> str:
    return YIELD.get(target_set, "lines_removed")


def write(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    SUMMARY.mkdir(parents=True, exist_ok=True)
    with (SUMMARY / f"{name}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    (SUMMARY / f"{name}.md").write_text("\n".join(lines) + "\n")


def fmt(mean: float, lo: float, hi: float, digits: int = 1) -> str:
    return f"{mean:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def groups(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        out.setdefault((r["target_set"], r["method"]), []).append(r)
    return out


def _values(recs: list[dict], key: str) -> list:
    """A metric over the runs that have it (invalid one-shot replies have no outcomes)."""
    return [r[key] for r in recs if r.get(key, "") != ""]


def main_table(rows: list[dict]) -> list[dict]:
    out = []
    by = groups(rows)
    for target_set in SET_ORDER:
        for method in METHOD_ORDER:
            recs = by.get((target_set, method))
            if not recs:
                continue
            row = {"target set": target_set, "method": method, "n": len(recs)}
            row["invalid output"] = sum(int(r.get("invalid_output") or 0) for r in recs)
            row["flaky hidden"] = sum(int(r.get("hidden_flaky") or 0) for r in recs)
            row["overload suspect"] = sum(int(r.get("overload_suspect") or 0) for r in recs)
            for key, name in METRICS:
                vals = _values(recs, key)
                digits = 2 if key == "hidden_changed" else 1
                row[f"{name} (mean, 95% CI)"] = fmt(*bootstrap_ci(vals), digits) if vals else "n/a"
            for key in ("format_edits", "import_edits"):
                vals = _values(recs, key)
                name = key.replace("_", " ")
                row[f"{name} (mean)"] = round(sum(vals) / len(vals), 1) if vals else "n/a"
            row["test runs (mean)"] = round(sum(r["test_runs"] for r in recs) / len(recs), 1)
            row["minutes (mean)"] = round(sum(r["minutes"] for r in recs) / len(recs), 1)
            # a run left over a laptop sleep inflates the mean (one Tier 2 run took 197 minutes)
            row["minutes (median)"] = round(statistics.median(r["minutes"] for r in recs), 1)
            out.append(row)
    return out


def paired_tests(rows: list[dict]) -> list[dict]:
    """Each method against cleansweep gatekeeper on the same targets."""
    index = {(r["target_set"], r["target"], r["method"]): r for r in rows}
    out = []
    for target_set in SET_ORDER:
        targets = sorted({t for s, t, m in index if s == target_set and m == REFERENCE})
        for method in METHOD_ORDER:
            if method == REFERENCE:
                continue
            pairs = [
                (index[(target_set, t, REFERENCE)], index[(target_set, t, method)])
                for t in targets
                if (target_set, t, method) in index
                and index[(target_set, t, method)]["lines_removed"] != ""
            ]
            if not pairs:
                continue
            # flaky and overload-suspect hidden changes ("" after read) count as unchanged
            b = sum(bool(m["hidden_changed"]) and not g["hidden_changed"] for g, m in pairs)
            c = sum(bool(g["hidden_changed"]) and not m["hidden_changed"] for g, m in pairs)
            key = yield_key(target_set)
            stat, p = wilcoxon([g[key] for g, _ in pairs], [m[key] for _, m in pairs])
            out.append(
                {
                    "target set": target_set,
                    "method vs gatekeeper": method,
                    "pairs": len(pairs),
                    "hidden changed only with method": b,
                    "hidden changed only with gatekeeper": c,
                    "McNemar exact p": round(mcnemar(b, c), 4),
                    "lines counted": YIELD_LABEL[key],
                    "lines removed: Wilcoxon W": round(stat, 1),
                    "Wilcoxon p": round(p, 4),
                }
            )
    return out


def ablation(rows: list[dict]) -> list[dict]:
    """What each part adds: probes (advisory vs guard_tests_only), judge (gatekeeper vs
    advisory), checks (cleansweep advisory vs tools_only)."""
    by = groups(rows)
    pairs = [
        ("differential probes", "cleansweep-advisory", "guard_tests_only"),
        ("judge as gatekeeper", "cleansweep-gatekeeper", "cleansweep-advisory"),
        ("Guard and Reviewer vs tools", "cleansweep-advisory", "tools_only"),
    ]
    out = []
    for target_set in SET_ORDER:
        for part, with_it, without in pairs:
            a, b = by.get((target_set, with_it)), by.get((target_set, without))
            if not a or not b:
                continue
            out.append(
                {
                    "target set": target_set,
                    "part": part,
                    "with": with_it,
                    "without": without,
                    "hidden changed with / without": (
                        f"{sum(_values(a, 'hidden_changed'))}/{len(_values(a, 'hidden_changed'))}"
                        f" vs {sum(_values(b, 'hidden_changed'))}/"
                        f"{len(_values(b, 'hidden_changed'))}"
                    ),
                    "lines removed with / without": f"{sum(_values(a, yield_key(target_set)))}"
                    f" vs {sum(_values(b, yield_key(target_set)))}",
                    "test runs with / without": f"{sum(r['test_runs'] for r in a)} vs "
                    f"{sum(r['test_runs'] for r in b)}",
                }
            )
    return out


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def figure_lines_removed(rows: list[dict]) -> None:
    by = groups(rows)
    sets = [s for s in SET_ORDER if any((s, m) in by for m in METHOD_ORDER)]
    fig, axes = plt.subplots(1, len(sets), figsize=(3.4 * len(sets), 2.8), facecolor=SURFACE)
    axes = axes if len(sets) > 1 else [axes]
    for ax, target_set in zip(axes, sets, strict=True):
        methods = [m for m in METHOD_ORDER if (target_set, m) in by]
        key = yield_key(target_set)
        stats = [bootstrap_ci(_values(by[(target_set, m)], key) or [0]) for m in methods]
        means = [s[0] for s in stats]
        errs = [[s[0] - s[1] for s in stats], [s[2] - s[0] for s in stats]]
        y = range(len(methods))
        ax.barh(
            list(y), means, xerr=errs, color=BAR, height=0.55, error_kw={"ecolor": INK_2, "lw": 1}
        )
        ax.set_yticks(list(y), methods)
        ax.invert_yaxis()
        n = len(by[(target_set, methods[0])])
        _style(ax, f"{target_set} (n={n})")
        ax.set_xlabel(f"{YIELD_LABEL[key]}\n(mean, 95% CI)", fontsize=8, color=INK_2)
    fig.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "main_lines_removed.png", dpi=200)
    plt.close(fig)


def figure_safety_vs_yield(rows: list[dict]) -> None:
    """Per method: lines removed per target against the share of targets whose hidden checks
    changed, both with 95% CIs. The AIDev panel uses a symlog x axis, since one-shot deletes
    whole files there."""
    by = groups(rows)
    sets = [s for s in SET_ORDER[1:] if any((s, m) in by for m in METHOD_ORDER)]
    if not sets:
        return
    fig, axes = plt.subplots(
        1, len(sets), figsize=(3.4 * len(sets), 3.0), facecolor=SURFACE, sharey=True
    )
    axes = axes if len(sets) > 1 else [axes]
    for ax, target_set in zip(axes, sets, strict=True):
        key = yield_key(target_set)
        for m in (m for m in METHOD_ORDER if (target_set, m) in by):
            x = bootstrap_ci(_values(by[(target_set, m)], key) or [0])
            y = bootstrap_ci(_values(by[(target_set, m)], "hidden_changed") or [0])
            label, colour, marker = MARKS[m]
            ax.errorbar(
                x[0],
                y[0],
                xerr=[[x[0] - x[1]], [x[2] - x[0]]],
                yerr=[[y[0] - y[1]], [y[2] - y[0]]],
                fmt=marker,
                color=colour,
                ecolor=colour,
                elinewidth=1,
                alpha=0.9,
                markersize=6,
                markeredgecolor=SURFACE,
                markeredgewidth=1,
                label=label,
            )
        n = len(by[(target_set, next(m for m in METHOD_ORDER if (target_set, m) in by))])
        _style(ax, f"{target_set} (n={n})")
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        if target_set == "aidev":
            ax.set_xscale("symlog", linthresh=10)
            ax.set_xlim(left=-1)
        ax.set_xlabel(f"{YIELD_LABEL[key]} (mean, 95% CI)", fontsize=8, color=INK_2)
    axes[0].set_ylabel("share with hidden behavior changed", fontsize=8, color=INK_2)
    axes[0].set_ylim(-0.05, 1.0)
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=len(labels),
        fontsize=7,
        frameon=False,
        labelcolor=INK,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / "safety_vs_yield.png", dpi=200)
    plt.close(fig)


def figure_guard_strength() -> None:
    path = SUMMARY / "guard_strength.csv"
    if not path.exists():
        return
    rows = [r for r in csv.DictReader(path.open()) if r["experiment"] == "mutation"]
    if not rows:
        return
    rows.sort(key=lambda r: (r["target_set"], r.get("probe_mode", "")))
    names = [
        f"{r['target_set']} ({r['probe_mode']})" if r.get("probe_mode") else r["target_set"]
        for r in rows
    ]
    tests = [float(r["share_by_tests"]) for r in rows]
    probes = [float(r["share_by_probes"]) for r in rows]
    fig, axes = plt.subplots(
        1, 2, figsize=(7.4, 0.5 + 0.35 * len(rows)), facecolor=SURFACE, sharey=True
    )
    for ax, vals, title in (
        (axes[0], tests, "caught by the tests"),
        (axes[1], probes, "caught only by the probes"),
    ):
        ax.barh(names, vals, color=BAR, height=0.55)
        for i, v in enumerate(vals):
            ax.text(v + 0.02, i, f"{v:.0%}", va="center", fontsize=8, color=INK)
        ax.set_xlim(0, 1.15)
        _style(ax, title)
    axes[0].invert_yaxis()
    fig.suptitle(
        "Mutants caught (share of mutants per target set)",
        x=0.02,
        ha="left",
        fontsize=10,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "guard_strength.png", dpi=200)
    plt.close(fig)


def main() -> int:
    rows = read(SUMMARY / "main_results.csv")
    write("main_table", main_table(rows))
    write("paired_tests", paired_tests(rows))
    write("ablation", ablation(rows))
    figure_lines_removed(rows)
    figure_safety_vs_yield(rows)
    figure_guard_strength()
    for name in ("main_table", "paired_tests", "ablation"):
        print((SUMMARY / f"{name}.md").read_text() if (SUMMARY / f"{name}.md").exists() else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
