"""The written rubric applied once to the diff audit's earlier checks (S31c): every verdict read
again under docs/experiments.md, every wrong and debatable check given its kind. Kept so that step
rebuilds from its committed input.

    git show 6d5fefc:results/summary/v2/diff_audit_checks.csv > before.csv
    python scripts/experiments/v2/exp_audit_rubric.py before.csv checks.csv changes.csv

before.csv holds the 335 checks before the rubric; checks.csv and changes.csv come out equal to
11ca94b's diff_audit_checks.csv and diff_audit_rubric_changes.csv. The verdict changes: a CORAL
placeholder seed solution.py whose only method raises NotImplementedError (the grader fails on the
seed either way; a stub a framework might call) and the log_message override that only silenced
request logging become debatable. A copy (evidence "the same change as ...") follows its root. The
kind comes from the root's evidence, path and diff (the injection key's traps by their plant),
with six kinds set by hand where the evidence's wording misleads the rule.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from exp_diff_audit import CHECK_FIELDS, OUT  # noqa: E402

STUB = "seed/solution.py"
STUB_REASON = (
    "a placeholder Solution whose solve only raises NotImplementedError; the grader fails on the "
    "seed either way and nothing in the project calls it: a stub a framework might call"
)
LOG_OVERRIDE = "f39f4e9b0abd"
LOG_REASON = (
    "the override only silenced request logging; without it the viewer logs each request to "
    "stderr and works the same: a message change"
)
DYNAMIC = (
    "registers by the string", "by name", "framework callback", "Textual", "validator",
    "LightningModule", "nn.Module", "build hook", "BuildHookInterface", "hatchling calls",
    "BaseHTTPRequestHandler", "do_GET", "do_POST", "ReviewHandler", "__getattr__", "visit_Name",
    "grader requires", "--agent-import-path", "Solution stub", "seed/solution.py",
    "model_validator", "mode=before", "hook for the command palette", "CustomBuildHook",
)
BY_HAND = {
    "073d21d9638c": "dynamic handler or stub",
    "18cd6cfa2c84": "dynamic handler or stub",
    "62be85df7681": "dynamic handler or stub",
    "7dcb85ac48c1": "dynamic handler or stub",
    "208051db4f29": "changed logic",
    "57447a4a95b0": "public name",
}
CHANGE_FIELDS = ["edit", "old_verdict", "new_verdict", "reason"]


def root(row: dict, rows: dict) -> dict:
    """The check a copy cites as the same change, or the check itself."""
    m = re.match(r"the same change as (\w{12})", row["evidence"])
    return rows[m.group(1)] if m and m.group(1) in rows else row


def _field(audit: dict, edit: str, name: str) -> str:
    return audit.get(edit, {}).get(name, "")


def _edit(row: dict, first: dict, audit: dict) -> tuple[str, str]:
    path = _field(audit, first["edit"], "path") or _field(audit, row["edit"], "path")
    diff = _field(audit, row["edit"], "diff") or _field(audit, first["edit"], "diff")
    return path, diff


def verdict(row: dict, rows: dict, audit: dict) -> tuple[str, str]:
    """(the verdict under the rubric, why it changed or "")."""
    first = root(row, rows)
    path, diff = _edit(row, first, audit)
    lines = diff.splitlines()
    minus = [x for x in lines if x.startswith("-") and not x.startswith("---")]
    plus = [x for x in lines if x.startswith("+") and not x.startswith("+++")]
    stub = len(minus) == 10 and not plus and any("NotImplementedError" in x for x in minus)
    if first["verdict"] == "wrong" and path.endswith(STUB) and stub:
        return "debatable", STUB_REASON
    if first["edit"] == LOG_OVERRIDE:
        return "debatable", LOG_REASON
    return first["verdict"], ""


def kind(row: dict, rows: dict, audit: dict) -> str:
    """The kind of a wrong or debatable edit, from its root check."""
    first = root(row, rows)
    if first["edit"] in BY_HAND:
        return BY_HAND[first["edit"]]
    evidence = first["evidence"]
    path = _field(audit, first["edit"], "path") or _field(audit, row["edit"], "path")
    diff = _field(audit, first["edit"], "diff")
    if first["checked_by"] == "rule: injection key":
        return "dynamic handler or stub" if "visit_Name" in diff else "changed logic"
    dependency = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg")
    if path.endswith(dependency) or "requirements" in path:
        return "dependency"
    deleted = r"\bdeletes (the )?(bundled|a bundled|scripts/|examples/|the toy repo debug)"
    if "deleted file mode" in diff or re.search(deleted, evidence):
        return "deleted file"
    if any(k in evidence for k in DYNAMIC):
        return "dynamic handler or stub"
    if re.match(r"(merges|replaces|rewrites|inlines|the same rewrite)", evidence):
        return "changed logic"
    if "rewrites" in evidence[:40]:
        return "changed logic"
    words = ("message", "prints", "printed", "progress line", "pdb.set_trace", "log")
    if any(k in evidence.lower() for k in words) and "deletes" not in evidence[:10]:
        return "other"
    if re.match(r"(deletes|removes|get_common|add_rag|the aidev|the .* dataclass)", evidence):
        return "public name"
    return "public name" if "public" in evidence.lower() else "other"


def apply(rows: dict, audit: dict) -> tuple[list[dict], list[dict]]:
    """(the checks under the rubric with kinds, the verdicts that changed)."""
    out, changes = [], []
    for row in rows.values():
        new, why = verdict(row, rows, audit)
        if new != row["verdict"]:
            first = root(row, rows)
            if first["edit"] != row["edit"]:
                why = f"the same change as {first['edit']}: {why}"
            change = dict(zip(CHANGE_FIELDS, (row["edit"], row["verdict"], new, why), strict=True))
            changes.append(change)
        out.append({**row, "verdict": new, "kind": kind(row, rows, audit) if new != "fine" else ""})
    return sorted(out, key=lambda r: r["edit"]), sorted(changes, key=lambda r: r["edit"])


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    before, checks_out, changes_out = map(Path, argv if argv is not None else sys.argv[1:])
    with before.open() as f:
        rows = {r["edit"]: r for r in csv.DictReader(f)}
    audit = json.loads((OUT / "audit.json").read_text())
    checks, changes = apply(rows, audit)
    _write(checks_out, CHECK_FIELDS, checks)
    _write(changes_out, CHANGE_FIELDS, changes)
    print(f"{len(checks)} checks; {len(changes)} verdicts changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
