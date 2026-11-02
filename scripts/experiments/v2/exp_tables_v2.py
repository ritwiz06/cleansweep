"""v2 tables: the agent team next to v1 (mean and 95% CI), paired tests, the ablations, and the
injection benchmark by category.

    python scripts/experiments/v2/exp_tables_v2.py

Reads results/summary/v2/eval_runs.csv (exp_collect_v2.py) and injection.csv (exp_inject.py
table). Writes results/summary/v2/{eval_table,eval_paired,ablations}.{csv,md} and
injection_summary.csv. Toy and demo pool as "answer keys"; their runs pair by target and repeat.
Hidden changes marked flaky count as no outcome. Hidden changes come from hidden tests and
planted items from answer keys; no LLM judges any measure here.
"""

from __future__ import annotations

import csv
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

from exp_inject import summarize  # noqa: E402
from methods_v2 import ABLATIONS  # noqa: E402

from cleansweep.eval.stats import bootstrap_ci, mcnemar, wilcoxon  # noqa: E402

# CLEANSWEEP_RESULTS points the tables at another results folder (reproduce_tables.sh DIR)
RESULTS = Path(os.environ.get("CLEANSWEEP_RESULTS", ROOT / "results"))
SUMMARY = RESULTS / "summary" / "v2"
SET_ORDER = ["answer keys", "swebench_t1", "swebench_t2", "aidev"]
REFERENCE = "cleansweep-gatekeeper"
MAIN = ["agentic", "agentic-rules", REFERENCE, "cleansweep-advisory"]
ABLATION_ORDER = ["agentic", *(f"agentic-{a}" for a in ABLATIONS), "agentic-rules"]
VERDICTS = ["everything runs", "nothing applied", "not verified"]
VERDICT_COLUMN = "verdicts: " + " / ".join(VERDICTS)
NUMBERS = [
    "repeat",
    "hidden_changed",
    "hits",
    "total",
    "code_lines_removed",
    "lines_removed",
    "llm_calls",
    "prompt_tokens",
    "completion_tokens",
    "test_runs",
    "hidden_flaky",
]


def read(path: Path) -> list[dict]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in NUMBERS:
            if r[k] != "":
                r[k] = int(r[k])
        r["minutes"] = float(r["minutes"])
        if r["hidden_flaky"] == 1:
            r["hidden_changed"] = ""
    return rows


def write(name: str, rows: list[dict], markdown: bool = True) -> None:
    if not rows:
        return
    SUMMARY.mkdir(parents=True, exist_ok=True)
    with (SUMMARY / f"{name}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if markdown:
        cols = list(rows[0])
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
        (SUMMARY / f"{name}.md").write_text("\n".join(lines) + "\n")


def fmt(mean: float, lo: float, hi: float, digits: int = 1) -> str:
    return f"{mean:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def _values(recs: list[dict], key: str) -> list:
    return [r[key] for r in recs if r[key] != ""]


def _mean(values: list) -> float | str:
    return round(sum(values) / len(values), 1) if values else "--"


def _share(recs: list[dict], ok) -> str:
    return f"{sum(1 for r in recs if ok(r))}/{len(recs)}"


def _verdicts(recs: list[dict]) -> str:
    return " / ".join(str(sum(r["verdict"] == v for r in recs)) for v in VERDICTS)


def _planted(recs: list[dict]) -> str:
    keyed = [r for r in recs if r["total"] != ""]
    return f"{sum(r['hits'] for r in keyed)}/{sum(r['total'] for r in keyed)}" if keyed else "--"


def groups(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        out.setdefault((r["target_set"], r["method"]), []).append(r)
    return out


def _cost(recs: list[dict]) -> dict:
    tokens = [r["prompt_tokens"] + r["completion_tokens"] for r in recs if r["prompt_tokens"] != ""]
    return {
        "test runs (mean)": _mean([r["test_runs"] for r in recs]),
        "LLM requests (mean)": _mean(_values(recs, "llm_calls")),
        "tokens (mean)": round(sum(tokens) / len(tokens)) if tokens else "--",
        "minutes (median)": round(statistics.median(r["minutes"] for r in recs), 1),
    }


def eval_table(rows: list[dict]) -> list[dict]:
    out = []
    by = groups(rows)
    for target_set in SET_ORDER:
        for method in MAIN:
            recs = by.get((target_set, method))
            if not recs:
                continue
            row = {
                "target set": target_set,
                "method": method,
                "n": len(recs),
                VERDICT_COLUMN: _verdicts(recs) if method.startswith("agentic") else "--",
                "planted found": _planted(recs),
            }
            for key, name, digits in (
                ("hidden_changed", "hidden changed", 2),
                ("code_lines_removed", "code lines removed", 1),
                ("lines_removed", "lines removed", 1),
            ):
                vals = _values(recs, key)
                row[f"{name} (mean, 95% CI)"] = fmt(*bootstrap_ci(vals), digits) if vals else "n/a"
            out.append(row | _cost(recs))
    return out


def eval_paired(rows: list[dict]) -> list[dict]:
    """The team (LLM and rule-based Manager) against v1's gatekeeper on the same targets and
    repeats: McNemar on hidden changes, Wilcoxon on code lines removed."""
    index = {(r["target_set"], r["target"], r["repeat"], r["method"]): r for r in rows}
    out = []
    for target_set in SET_ORDER:
        keys = sorted({(t, k) for s, t, k, m in index if s == target_set and m == REFERENCE})
        for method in ("agentic", "agentic-rules"):
            pairs = [
                (index[(target_set, t, k, REFERENCE)], index[(target_set, t, k, method)])
                for t, k in keys
                if (target_set, t, k, method) in index
            ]
            if not pairs:
                continue
            # no-outcome hidden results ("") count as unchanged, as in v1's paired tests
            b = sum(bool(m["hidden_changed"]) and not v["hidden_changed"] for v, m in pairs)
            c = sum(bool(v["hidden_changed"]) and not m["hidden_changed"] for v, m in pairs)
            ours = [m["code_lines_removed"] for _, m in pairs]
            theirs = [v["code_lines_removed"] for v, _ in pairs]
            stat, p = wilcoxon(ours, theirs)
            out.append(
                {
                    "target set": target_set,
                    "method vs v1 gatekeeper": method,
                    "pairs": len(pairs),
                    "hidden changed only with method": b,
                    "hidden changed only with v1": c,
                    "McNemar exact p": round(mcnemar(b, c), 4),
                    "code lines removed, method vs v1 (total)": f"{sum(ours)} vs {sum(theirs)}",
                    "Wilcoxon W": round(stat, 1),
                    "Wilcoxon p": round(p, 4),
                }
            )
    return out


def ablations(rows: list[dict], plants: list[dict]) -> list[dict]:
    """Quality, safety and cost of each ablation next to the full team: the answer keys
    (planted items found) and the injected set (planted slop removed, traps removed)."""
    by = groups(rows)
    out = []
    for method in ABLATION_ORDER:
        recs = by.get(("answer keys", method))
        if not recs:
            continue
        hidden = _values(recs, "hidden_changed")
        out.append(
            {
                "set": "answer keys",
                "method": method,
                "runs": len(recs),
                "planted found": _planted(recs),
                "traps removed": "--",
                "hidden changed": f"{sum(hidden)}/{len(hidden)}",
                VERDICT_COLUMN: _verdicts(recs),
                **_cost(recs),
            }
        )
    for method in ABLATION_ORDER:
        mine = [p for p in plants if p["method"] == method]
        if not mine:
            continue
        runs = list({(p["repo"], p["seed"]): p for p in mine}.values())
        slop = [p for p in mine if p["kind"] == "slop"]
        traps = [p for p in mine if p["kind"] == "trap"]
        out.append(
            {
                "set": "injected",
                "method": method,
                "runs": len(runs),
                "planted found": f"{sum(p['removed'] for p in slop)}/{len(slop)}",
                "traps removed": f"{sum(p['removed'] for p in traps)}/{len(traps)}",
                "hidden changed": _share(runs, lambda p: p["hidden_changed"]),
                VERDICT_COLUMN: "--",
                "test runs (mean)": _mean([int(p["test_runs"]) for p in runs]),
                "LLM requests (mean)": _mean([int(p["llm_calls"]) for p in runs]),
                "tokens (mean)": "--",
                "minutes (median)": round(statistics.median(float(p["minutes"]) for p in runs), 1),
            }
        )
    return out


def read_plants(path: Path) -> list[dict]:
    with path.open() as f:
        plants = list(csv.DictReader(f))
    for p in plants:
        p["removed"] = int(p["removed"])
        p["hidden_changed"] = p["hidden_changed"] == "True"
    return plants


def main() -> int:
    runs, injection = SUMMARY / "eval_runs.csv", SUMMARY / "injection.csv"
    rows = read(runs) if runs.exists() else []
    plants = read_plants(injection) if injection.exists() else []
    write("eval_table", eval_table(rows))
    write("eval_paired", eval_paired(rows))
    write("ablations", ablations(rows, plants))
    if plants:
        write("injection_summary", summarize(plants), markdown=False)
    for name in ("eval_table", "eval_paired", "ablations"):
        path = SUMMARY / f"{name}.md"
        print(path.read_text() if path.exists() else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
