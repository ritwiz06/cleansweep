"""Review sheets for the case studies, and their acceptance rates.

    python scripts/experiments/v2/exp_review_sheet.py NAME --safe RUN --thorough RUN
    python scripts/experiments/v2/exp_review_sheet.py NAME --score

RUN is a case-study record folder under results/raw/case_studies/ (its report.json). The sheet,
results/raw/case_studies/NAME/review_sheet.md, has one row per change applied in safe mode, per
suggestion left in safe mode, and per change thorough mode made beyond safe mode (kept, or tried
and rolled back by its checks), each with its evidence and how it was checked. review_rows.json
beside it locates each row's item in its run, for exp_llm_review.py.

Two decision columns: "LLM reviewer" (with its votes and reason), filled in by
exp_llm_review.py (an independent model, blinded: not a human evaluation), and "human
decision", left for a person (accept, reject or unsure). --score writes review_scores.csv:
acceptance (accepted / decided) by category and mode, for each column that has decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
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
REVIEW = ["LLM reviewer", "votes", "LLM reviewer reason", "human decision", "note"]
HEADER = "| " + " | ".join([*COLUMNS, *REVIEW]) + " |"
LABEL = "LLM-reviewer acceptance (independent model, blinded)"


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


def _rows(report: SweepReport, run: str, mode: str, kinds: set[str], skip: set[str]) -> list:
    """Rows of one run. Kinds: "applied" (kept), "suggestion", and "tried" (a change thorough
    mode made beyond safe mode that its checks rolled back or could not apply)."""
    results = {r.item_id: r for r in report.results}
    rows = []
    for item in report.plan.items:
        result = results.get(item.item_id)
        status = result.status if result else "-"
        if status in KEPT:
            kind = "applied"
        elif "thorough" in item.sources:
            kind = "tried"
        elif item.lane == "suggest":
            kind = "suggestion"
        else:
            kind = "not applied"
        if kind not in kinds or item.unit.key in skip:
            continue
        rows.append(
            {
                "run": run,
                "item_id": item.item_id,
                "mode": mode,
                "kind": kind,
                "item": item.unit.key,
                "category": item.category,
                "what": f"{item.action}: {item.reason}",
                "evidence": "; ".join(item.evidence[:3]),
                "checked": _checked(result) if kind in ("applied", "tried") else "-",
                "why": result.notes if kind == "tried" and result else "",
                "outcome": status,
            }
        )
    return rows


def sheet_rows(safe: str, thorough: str | None) -> list[dict]:
    """The rows of a sheet: safe-mode changes and suggestions, then thorough mode's extras."""
    rows = _rows(
        load_json(SweepReport, CASES / safe / "report.json"),
        safe,
        "safe",
        {"applied", "suggestion"},
        set(),
    )
    if thorough:
        report = load_json(SweepReport, CASES / thorough / "report.json")
        kept_safe = {r["item"] for r in rows if r["kind"] == "applied"}
        rows += _rows(report, thorough, "thorough", {"applied", "tried"}, kept_safe)
    for n, row in enumerate(rows, 1):
        row["n"] = n
    return rows


def _decisions(path: Path, column: str) -> dict[int, str]:
    """A filled-in column of an existing sheet, by row number."""
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    header = next((ln for ln in lines if ln.startswith("| # |")), None)
    if header is None:
        return {}
    names = [c.strip() for c in header.split("|")[1:-1]]
    if column not in names:
        return {}
    index = names.index(column)
    out = {}
    for line in lines:
        if re.match(r"^\| \d+ \|", line):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
            if cells[index]:
                out[int(cells[0])] = cells[index]
    return out


def write_sheet(name: str, safe: str, thorough: str | None, reviews: dict | None = None) -> Path:
    """Write the sheet and review_rows.json; reviews (row -> LLM review) fill the LLM columns.
    A person's decisions and notes already in the sheet are kept."""
    path = CASES / name / "review_sheet.md"
    human, notes = _decisions(path, "human decision"), _decisions(path, "note")
    rows = sheet_rows(safe, thorough)
    lines = [
        f"# Review sheet: {name}",
        "",
        f"Safe-mode run: `{safe}`" + (f"; thorough-mode run: `{thorough}`" if thorough else ""),
        "(records in `results/raw/case_studies/`). Nothing here was applied to the original.",
        "",
        "Rows with mode `thorough` are the changes thorough mode made beyond safe mode: `applied`",
        "(kept) or `tried` (its checks rolled it back).",
        "",
        f"**LLM reviewer** is an independent model ({LABEL}): a different model from the agents',",
        "shown only the code, the proposed change and the facts, never the agents' verdict, lane,",
        "mode or reasons; 3 votes per row, the majority decides. It is not a human evaluation.",
        "**human decision** is for a person: `accept`, `reject` or `unsure`.",
        "",
        HEADER,
        "|" + "---|" * (len(COLUMNS) + len(REVIEW)),
    ]
    for row in rows:
        n = row["n"]
        review = (reviews or {}).get(n) or {}
        cells = [str(n), row["mode"], row["kind"], f"`{_cell(row['item'], 120)}`"]
        checked = row["checked"] + (f"; not kept: {row['why']}" if row["why"] else "")
        cells += [row["category"], _cell(row["what"]), _cell(row["evidence"]), _cell(checked)]
        cells += [row["outcome"], review.get("decision", ""), ", ".join(review.get("votes", []))]
        cells += [_cell(review.get("reason", ""), 200), human.get(n, ""), notes.get(n, "")]
        lines.append("| " + " | ".join(cells) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = {"name": name, "safe": safe, "thorough": thorough, "rows": rows}
    (path.parent / "review_rows.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return path


def score(name: str) -> Path:
    """review_scores.csv: per category and mode, the LLM reviewer's and the human's decisions."""
    path = CASES / name / "review_sheet.md"
    rows = json.loads((path.parent / "review_rows.json").read_text())["rows"]
    columns = {"llm": _decisions(path, "LLM reviewer"), "human": _decisions(path, "human decision")}
    counts: dict[tuple[str, str], dict[str, Counter]] = {}
    for row in rows:
        key = (row["category"], f"{row['mode']} {row['kind']}")
        for who, decided in columns.items():
            value = decided.get(row["n"], "").lower()
            cell = counts.setdefault(key, {}).setdefault(who, Counter())
            cell[value if value in DECISIONS else "blank"] += 1
    out = path.parent / "review_scores.csv"
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        head = ["category", "mode", "rows"]
        for who in ("llm", "human"):
            head += [f"{who}_{k}" for k in (*DECISIONS, "blank", "rate")]
        writer.writerow(head)
        for (category, mode), by in sorted(counts.items()):
            line = [category, mode, sum(by["llm"].values())]
            for who in ("llm", "human"):
                c = by[who]
                decided = c["accept"] + c["reject"]
                rate = round(c["accept"] / decided, 3) if decided else ""
                line += [c["accept"], c["reject"], c["unsure"], c["blank"], rate]
            writer.writerow(line)
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
