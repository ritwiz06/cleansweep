"""Review sheets for the case studies, and their acceptance rates once a person has filled them in.

    python scripts/experiments/v2/exp_review_sheet.py NAME --safe RUN --thorough RUN
    python scripts/experiments/v2/exp_review_sheet.py NAME --score

RUN is a case-study record folder under results/raw/case_studies/ (its report.json). The sheet,
results/raw/case_studies/NAME/review_sheet.md, has one row per change applied in safe mode, per
suggestion left in safe mode, and per change thorough mode applied beyond safe mode, each with
its evidence and how it was checked, and an empty "decision" column for the reviewer: accept,
reject or unsure. --score reads the filled sheet and writes review_scores.csv: acceptance rate
(accepted / decided) by category and mode, with the unsure and blank counts.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cleansweep.core.io import load_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402

CASES = ROOT / "results" / "raw" / "case_studies"
KEPT = ("kept", "repaired")
DECISIONS = ("accept", "reject", "unsure")
COLUMNS = ["#", "mode", "kind", "item", "category", "what", "evidence", "checked by", "outcome"]
HEADER = "| " + " | ".join([*COLUMNS, "decision", "note"]) + " |"


def _cell(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _checked(result) -> str:
    if result is None:
        return "not applied"
    parts = []
    if result.tests is not None:
        t = result.tests
        parts.append(f"tests {t.passed} passed, {t.failed} failed")
    if result.ast_equal:
        parts.append("AST unchanged")
    if result.diff_check is not None:
        d = result.diff_check
        parts.append(f"probes {d.n_cases} cases, {'same' if d.same else 'changed'}")
    return "; ".join(parts) or "tests"


def _rows(report: SweepReport, mode: str, kinds: set[str], skip: set[str]) -> list[dict]:
    results = {r.item_id: r for r in report.results}
    rows = []
    for item in report.plan.items:
        result = results.get(item.item_id)
        status = result.status if result else "-"
        if status in KEPT:
            kind = "applied"
        elif item.lane == "suggest":
            kind = "suggestion"
        else:
            kind = f"applied, {status}" if result else "not applied"
        if kind not in kinds or item.unit.key in skip:
            continue
        rows.append(
            {
                "mode": mode,
                "kind": kind,
                "item": item.unit.key,
                "category": item.category,
                "what": f"{item.action}: {item.reason}",
                "evidence": "; ".join(item.evidence[:3]),
                "checked": _checked(result) if kind == "applied" else "-",
                "outcome": status,
            }
        )
    return rows


def write_sheet(name: str, safe: str, thorough: str | None) -> Path:
    safe_report = load_json(SweepReport, CASES / safe / "report.json")
    rows = _rows(safe_report, "safe", {"applied", "suggestion"}, set())
    if thorough:
        report = load_json(SweepReport, CASES / thorough / "report.json")
        kept_safe = {r["item"] for r in rows if r["kind"] == "applied"}
        rows += _rows(report, "thorough", {"applied"}, kept_safe)
    lines = [
        f"# Review sheet: {name}",
        "",
        f"Safe-mode run: `{safe}`" + (f"; thorough-mode run: `{thorough}`" if thorough else ""),
        "(records in `results/raw/case_studies/`). Nothing here was applied to the original.",
        "",
        "Fill in **decision** for every row: `accept` (you would keep this change, or act on",
        "this suggestion), `reject` (you would not), or `unsure`. **note** is optional. Rows with",
        "mode `thorough` are the changes thorough mode applied beyond safe mode.",
        "",
        HEADER,
        "|" + "---|" * 11,
    ]
    for n, row in enumerate(rows, 1):
        cells = [str(n), row["mode"], row["kind"], f"`{_cell(row['item'], 120)}`"]
        cells += [row["category"], _cell(row["what"]), _cell(row["evidence"]), row["checked"]]
        cells += [row["outcome"], "", ""]
        lines.append("| " + " | ".join(cells) + " |")
    path = CASES / name / "review_sheet.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def score(name: str) -> Path:
    text = (CASES / name / "review_sheet.md").read_text(encoding="utf-8")
    counts: dict[tuple[str, str], Counter] = {}
    for line in text.splitlines():
        if not re.match(r"^\| \d+ \|", line):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        mode, kind, category, decision = cells[1], cells[2], cells[4], cells[9].lower()
        key = (category, f"{mode} {kind}")
        counts.setdefault(key, Counter())[decision if decision in DECISIONS else "blank"] += 1
    out = CASES / name / "review_scores.csv"
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "mode", "rows", "accept", "reject", "unsure", "blank", "rate"])
        for (category, mode), c in sorted(counts.items()):
            decided = c["accept"] + c["reject"]
            rate = round(c["accept"] / decided, 3) if decided else ""
            row = [category, mode, sum(c.values()), c["accept"], c["reject"], c["unsure"]]
            writer.writerow(row + [c["blank"], rate])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--safe")
    parser.add_argument("--thorough")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args(argv)
    if args.score:
        print(score(args.name))
    elif args.safe:
        print(write_sheet(args.name, args.safe, args.thorough))
    else:
        parser.error("give --safe RUN (and --thorough RUN), or --score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
