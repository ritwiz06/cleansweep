"""Agreement on the human-rating packet (C8): Cohen's kappa between the two raters, and between
each rater and the recorded label (key.json's llm_label: the diff audit's verdict, auditor "no"
as fine; the LLM reviewer's decision as accept = fine, unsure = debatable, reject = wrong), with
the raw agreement and a 95% bootstrap CI over items (2000 resamples, seed 572), on the three
labels and on wrong vs not wrong, for all items, per source and per tier. Unweighted over the
items rated: the sample over-represents wrong labels (key.json has each item's weight).

    python scripts/experiments/v3/exp_human_kappa.py [PACKET] [--out CSV]

PACKET defaults to .notes/report/human_rating/ (rater_A.csv, rater_B.csv, key.json). Writes
results/summary/v3/human_kappa.csv; while a sheet is missing or has no labels, one row saying
"not human-validated" instead of numbers.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v2"))

from exp_llm_review import cohen  # noqa: E402

PACKET = ROOT / ".notes" / "report" / "human_rating"
OUT = ROOT / "results" / "summary" / "v3" / "human_kappa.csv"
LABELS = ("wrong", "debatable", "fine")
SUBSETS = ("all", "diff audit", "diff audit (LLM-judged)", "diff audit (confirmed)", "review sheet")
RESAMPLES = 2000
SEED = 572
FIELDS = ["comparison", "subset", "scale", "n", "agreement", "kappa", "ci_low", "ci_high"]


def read_sheet(path: Path) -> dict[str, str]:
    """item -> label of a rater sheet; blank and unknown labels are left out."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    labels = {r["item"].strip(): (r.get("label") or "").strip().lower() for r in rows}
    return {item: label for item, label in labels.items() if label in LABELS}


def subsets(item: dict) -> list[str]:
    """The subsets an item counts in."""
    if item["source"] != "diff audit":
        return ["all", item["source"]]
    tier = "confirmed" if item["tier"] == "confirmed" else "LLM-judged"
    return ["all", "diff audit", f"diff audit ({tier})"]


def binary(label: str) -> str:
    return "wrong" if label == "wrong" else "not wrong"


def agreement(pairs: list[tuple[str, str]], seed: int = SEED) -> dict:
    """n, raw agreement, Cohen's kappa and its 95% bootstrap CI over items."""
    rng = random.Random(seed)
    kappas = []
    for _ in range(RESAMPLES):
        pick = [rng.choice(pairs) for _ in pairs]
        kappas.append(cohen([a for a, _ in pick], [b for _, b in pick]))
    kappas.sort()
    return {
        "n": len(pairs),
        "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3),
        "kappa": cohen([a for a, _ in pairs], [b for _, b in pairs]),
        "ci_low": kappas[int(0.025 * RESAMPLES)],
        "ci_high": kappas[int(0.975 * RESAMPLES) - 1],
    }


def table(items: dict, a: dict, b: dict) -> list[dict]:
    """One row per comparison, subset and scale with at least one item both sides labeled."""
    llm = {n: item["llm_label"] for n, item in items.items() if item["llm_label"] in LABELS}
    status = "human-validated"
    if not len(a) == len(b) == len(items):
        status = f"partial: rater_A {len(a)}, rater_B {len(b)} of {len(items)} items labeled"
    comparisons = {
        "rater_A vs rater_B": (a, b),
        "rater_A vs LLM": (a, llm),
        "rater_B vs LLM": (b, llm),
    }
    rows = []
    for name, (x, y) in comparisons.items():
        for subset in SUBSETS:
            both = [n for n in sorted(items, key=int) if n in x and n in y]
            both = [n for n in both if subset in subsets(items[n])]
            if not both:
                continue
            for scale, collapse in (("3 labels", str), ("wrong vs not wrong", binary)):
                pairs = [(collapse(x[n]), collapse(y[n])) for n in both]
                row = {"comparison": name, "subset": subset, "scale": scale}
                rows.append({**row, **agreement(pairs), "status": status})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packet", nargs="?", type=Path, default=PACKET)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    key = args.packet / "key.json"
    sheets = {name: read_sheet(args.packet / name) for name in ("rater_A.csv", "rater_B.csv")}
    empty = [name for name, labels in sheets.items() if not labels]
    if not key.exists() or empty:
        why = "no key.json" if not key.exists() else " and ".join(empty) + " missing or blank"
        rows = [{**dict.fromkeys(FIELDS, ""), "status": f"not human-validated: {why}"}]
    else:
        rows = table(json.loads(key.read_text())["items"], *sheets.values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*FIELDS, "status"])
        writer.writeheader()
        writer.writerows(rows)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
