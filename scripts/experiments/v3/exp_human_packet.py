"""The human-rating packet (C8): 100 changes for two people to label, drawn from the v2 diff
audit's kept code edits and the case-study review sheets, blinded and shuffled.

    python scripts/experiments/v3/exp_human_packet.py [OUT] [--root CHECKOUT]

OUT defaults to .notes/report/human_rating/. --root is the checkout whose results and notes are
read (default: this one); its v2 scripts collect the edits, so their data paths resolve there.

One item is one change: identical edits of another seed or run are merged (same repository, file,
removed and added lines and enclosing class or function, as exp_diff_audit.py's match). An item
shows what its model saw, trimmed for reading: the project by name, the file, up to 12 lines of
code above the change, the diff, and where the removed names appear (diff audit) or the facts
(review sheet). Nothing names the method, the run, the seed or a label.

Diff-audit changes are drawn per stratum, method group x label: the method group is the first of
GROUPS whose runs made the change; the label is the audit's verdict with its tier, or "auditor
no". QUOTAS gives the items per label, spread evenly over the method groups, so the rare wrong
labels are drawn far above their share. Review-sheet items are applied or tried changes the LLM
reviewer accepted or rejected, likewise by decision and method group. The 20 edits of the audit's
calibration sheet and the 20 rows of the reviewer's calibration sheet are always in and count
toward their strata. An item's weight: changes in its stratum / items drawn from it. Seed 572.

Writes README.md, rubric.md, items.html and items.md (the same items), rater_A.csv and
rater_B.csv (blank labels), and key.json (sources and recorded labels; not for raters).
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".notes" / "report" / "human_rating"
SEED = 572
CONTEXT = 12  # lines of code shown above a change
GROUPS = ("team", "no research", "single agent", "v1", "other ablation", "one-shot LLM")
METHOD_GROUP = {
    "agentic": "team",
    "agentic (thorough)": "team",
    "agentic-no_research": "no research",
    "agentic-single_agent": "single agent",
    "cleansweep": "v1",
    "cleansweep-gatekeeper": "v1",
    "cleansweep-advisory": "v1",
    "one_shot_llm": "one-shot LLM",
}
POOLS = ("diff audit", "review edit", "review suggestion")
# items per (pool, label); a label without a quota gets only its calibration items
QUOTAS = {
    ("diff audit", "wrong, confirmed"): 12,
    ("diff audit", "wrong, reading"): 18,
    ("diff audit", "debatable, reading"): 14,
    ("diff audit", "fine, confirmed"): 6,
    ("diff audit", "fine, reading"): 8,
    ("diff audit", "auditor no"): 12,
    ("review edit", "reject"): 5,
    ("review edit", "accept"): 5,
}
DECISION_LABEL = {"accept": "fine", "unsure": "debatable", "reject": "wrong"}
QUESTIONS = {
    "behavior": "Does this edit change behavior anyone could observe?",
    "maintainer": "As this project's maintainer, would you accept this change? "
    "(accept = fine, reject = wrong, unsure = debatable)",
}
RUN_PATH = re.compile(r"quarantined at|/Users/|/private/|cleansweep-runs")
LEAK = re.compile(
    r"agentic|single[_ ]agent|no[_ ]research|gatekeeper|one[_ ]shot|-abl-|cleansweep-runs"
    r"|results/raw|case_studies|quarantined|__r\d|/Users/|/private/",
    re.IGNORECASE,
)
WARNING = (
    "NOT FOR RATERS: this file holds each item's source, method, run and recorded labels. "
    "Do not open it before both rating sheets are done."
)
SHEET_FIELDS = ["item", "label", "confidence", "minutes", "note"]
README = """# Human rating

Do not open key.json: it holds the hidden answers and spoils the rating.

1. Read rubric.md (one page).
2. Open items.html in a browser (items.md has the same items): 100 items, about 2 hours.
3. Rater A fills rater_A.csv, rater B fills rater_B.csv, one row per item: label = wrong,
   debatable or fine; confidence = 1 (a guess) to 3 (sure); minutes and note optional.
4. Rate alone and only from what the item shows; talk about items only after both sheets are done.
5. Time it: note when you start and stop, and write the total minutes in the last row's note.
6. Save as plain CSV (keep the header and the item column) and send it back.
"""
RUBRIC = """# Rubric

Give every item one label, **wrong**, **debatable** or **fine**, and a confidence: 1 = a guess,
2 = fairly sure, 3 = sure. Judge only from what the item shows. Each item says its question.

## Behavior: "Does this edit change behavior anyone could observe?"

Anyone: a user of the program, code that imports or calls it (also from outside the project, for
a library), a script, a test, the package build or its installed dependencies.

- **wrong:** the edit changes behavior that something in the project or its users can actually
  trigger: a caller in the project (direct, by a string, through a decorator registration, or a
  framework callback the project's own entry points trigger, such as a web handler's `do_GET`, a
  Textual `compose`, a pydantic validator or a build hook); the project's tests, scripts or
  examples; a command, option or page users reach through the documented interface, or a call the
  docs or the project's own messages tell users to make; a dependency something imports after a
  fresh install; a message users depend on (documented, or the only report of a failure). Code
  that stays but computes something else (two near-duplicates that differ, merged) is wrong too.
- **debatable:** the edit removes code reachable only from outside the project (a public name
  nothing in the project calls or documents; a handler or stub a framework might call but nothing
  in the project triggers, such as a placeholder whose only method raises `NotImplementedError`),
  or its intent is unclear (a progress or debug message, a version pin or floor that only changes
  what a fresh install resolves).
- **fine:** no observable change: unused private code, a comment, an import of a module without
  side effects, a dependency nothing imports.

"Where removed names appear" lists the lines of the project, before the edit, that name what the
edit removes ("nowhere else": no other file names it).

## Maintainer: "As this project's maintainer, would you accept this change?"

Some items are changes or suggestions from a review sheet. Answer as the maintainer: **fine** =
accept (you would merge it, or act on the suggestion), **wrong** = reject, **debatable** = unsure
(you would need more information). Is it correct, does it keep behavior, is it worth having?

## Worked examples (not among the items)

1. Behavior: removes `import json` from a module that never uses `json`. **fine**: an unused
   import of a module without side effects.
2. Behavior: deletes `visit_Call(self, node)` from a subclass of `ast.NodeVisitor`; the project
   calls `.visit(tree)` on it and prints the count it keeps. **wrong**: the visitor calls it by
   name, so the printed count changes.
3. Behavior: deletes `to_dict(self)` from a public class of an installable library; nothing in the
   project calls or documents it. **debatable**: reachable only from outside the project.

Between two labels, pick the closer one and give confidence 1; put anything worth knowing in the
note.
"""
CSS = """
body { background: #fff; color: #1b1b1b; margin: 0 auto; max-width: 62rem; padding: 1rem;
  font: 15px/1.5 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
.item { border-top: 2px solid #444; margin-top: 1.6rem; padding-top: .4rem; }
h2 { font-size: 1.2rem; margin: .2rem 0 .4rem; break-after: avoid; }
.q { background: #f4f1e6; border-left: 4px solid #8a6d00; padding: .3rem .6rem; }
pre { background: #f7f7f7; border: 1px solid #d0d0d0; padding: .5rem; white-space: pre-wrap;
  overflow-wrap: anywhere; font: 12.5px/1.4 Menlo, Consolas, monospace; }
code { background: #f0f0f0; padding: 0 .2em; font: 12.5px Menlo, Consolas, monospace; }
.add { background: #e3f4e3; color: #0f5a1e; }
.del { background: #fbe6e6; color: #8a1020; }
.hunk { color: #666; }
@media print { body { max-width: none; } .item { break-inside: avoid-page; }
  .add, .del, .q { print-color-adjust: exact; -webkit-print-color-adjust: exact; } }
"""


def method_group(methods) -> str:
    """The first of GROUPS that any of the methods belongs to."""
    found = {METHOD_GROUP.get(m, "other ablation") for m in methods}
    return next(g for g in GROUPS if g in found)


def sheet_group(sheet: str) -> str:
    """The method group of a review sheet: an ablation sheet's method, else the team."""
    ablation = sheet.partition("-abl-")[2]
    return method_group([f"agentic-{ablation}" if ablation not in ("", "team") else "agentic"])


def project_name(project: str) -> str:
    """A project as raters see it: the repository or task, without commit, dataset or run."""
    project = project.split("@")[0]
    kind, _, rest = project.partition(":")
    if kind == "swebench":
        return rest.split(":")[0]
    if kind == "local" and rest.startswith(("self", "cleansweep")):
        return "cleansweep"  # this repository, run from a copy
    return rest or project


def change_lines(diff: str) -> tuple[str, ...]:
    return tuple(x for x in diff.splitlines() if x[:1] in "+-" and not x.startswith(("+++", "---")))


def clean_diff(diff: str, cut: bool = False) -> str:
    """The diff without its git header lines, marked where the model's view cut it."""
    lines = [x for x in diff.splitlines() if not x.startswith(("diff --git", "index "))]
    if cut:
        lines.append("[the diff goes on; the view was cut here]")
    return "\n".join(lines).strip("\n")


def above(code: str, diff: str) -> str:
    """The numbered code lines just above the diff's first hunk (all of them without a diff)."""
    hunk = re.search(r"^@@ -(\d+)", diff, re.M)
    if not hunk:
        return code
    first = int(hunk.group(1))
    keep = []
    for line in code.splitlines():
        number = re.match(r"\s*(\d+) ", line)
        if number and first - CONTEXT <= int(number.group(1)) < first:
            keep.append(line)
    return "\n".join(keep)


def audit_item(edit: dict) -> dict:
    """The parts of the auditor's view of an edit that a rater sees."""
    view, diff = edit["view"], edit["diff"][:5000]
    code = view.partition("Code before the edit:\n```\n")[2].partition("\n```\n\nDiff:\n")[0]
    start = view.rfind("\nWhere removed names appear")
    where = view[start + 1 :] if start >= 0 else "Where removed names appear"
    head, _, rest = where.partition("\n")
    title, _, note = head.removesuffix(":").partition(": ")  # "...: not searched (...)"
    return {
        "question": "behavior",
        "project": project_name(edit["project"]),
        "file": f"`{edit['path']}`",
        "code": above(code, diff),
        "diff": clean_diff(diff, len(edit["diff"]) > 5000),
        "notes_title": title,
        "notes": [x.removeprefix("- ") for x in rest.splitlines()] or ([note] if note else []),
    }


def review_item(view: str, project: str) -> dict:
    """The parts of the LLM reviewer's view of a row that a rater sees, with the project named as
    in the diff audit and no run paths."""
    head = dict(x.split(": ", 1) for x in view.split("\n\n")[0].splitlines() if ": " in x)
    code = view.partition("\nCode:\n```\n")[2].partition("\n```\n\nProposed: ")[0]
    diff = view.partition("\nDiff:\n```diff\n")[2].rpartition("\n```\n\nFacts:\n")[0]
    facts = view.rpartition("\nFacts:\n")[2].splitlines()
    return {
        "question": "maintainer",
        "project": project_name(project),
        "file": head.get("Location", ""),
        "kind": head.get("Kind", ""),
        "code": above(code, diff),
        "proposed": view.partition("\n\nProposed: ")[2].split("\n\n")[0],
        "diff": clean_diff(diff, len(diff) >= 4000),
        "notes_title": "Facts",
        "notes": [x.removeprefix("- ") for x in facts if not RUN_PATH.search(x)],
    }


def audit_changes(edits: list[dict], forced: list[str]) -> list[dict]:
    """The diff audit's changes: edits merged by their `same` key, each shown by its calibration
    edit, else its first checked edit, else its first edit."""
    by_key: dict[str, list[dict]] = {}
    for edit in sorted(edits, key=lambda e: e["edit"]):
        by_key.setdefault(edit["same"], []).append(edit)
    out = []
    for group in by_key.values():
        shown = min(group, key=lambda e: (e["edit"] not in forced, not e["verdict"], e["edit"]))
        if shown["verdict"]:
            label = f"{shown['verdict']}, {shown['tier']}"
        else:
            label = "auditor no" if shown["answer"] == "no" else f"open, {shown['answer']}"
        methods = Counter()
        for edit in group:
            methods.update(edit["methods"])
        out.append(
            {
                "id": shown["edit"],
                "pool": "diff audit",
                "label": label,
                "group": method_group(methods),
                "forced": shown["edit"] in forced,
                "match": (shown["path"], change_lines(shown["diff"][:4000])),
                "llm_label": shown["verdict"] or ("fine" if shown["answer"] == "no" else ""),
                "item": audit_item(shown),
                "key": {
                    "source": "diff audit",
                    "edit": shown["edit"],
                    "edits": [e["edit"] for e in group],
                    "project": shown["project"],
                    "path": shown["path"],
                    "auditor": shown["answer"],
                    "auditor_votes": shown["votes"],
                    "verdict": shown["verdict"],
                    "checked_by": shown["checked_by"],
                    "tier": shown["tier"] or "auditor",
                    "methods": dict(sorted(methods.items())),
                    "runs": sorted({r for e in group for r in e["runs"]}),
                    "calibration": f"audit sheet {forced.index(shown['edit']) + 1}"
                    if shown["edit"] in forced
                    else "",
                },
            }
        )
    return out


def review_changes(rows: list[dict], forced: list[tuple[str, int]]) -> list[dict]:
    """The reviewed rows of the case-study sheets, merged when several sheets show the same
    change (project, file and diff, or the same proposal)."""

    def order(row: dict) -> tuple:
        place = (row["sheet"], row["row"])
        return place not in forced, GROUPS.index(sheet_group(row["sheet"])), place

    by_key: dict[tuple, list[tuple[dict, dict]]] = {}
    for row in sorted(rows, key=order):
        item = review_item(row["view"], row["project"])
        same = (item["project"], item["file"], change_lines(item["diff"]) or item["proposed"])
        by_key.setdefault(same, []).append((row, item))
    out = []
    for group in by_key.values():
        row, item = group[0]
        place = (row["sheet"], row["row"])
        path = re.match(r"`([^`]*)`", item["file"])
        out.append(
            {
                "id": f"{row['sheet']}#{row['row']}",
                "pool": "review edit"
                if row["kind"] in ("applied", "tried")
                else "review suggestion",
                "label": row["decision"],
                "group": sheet_group(row["sheet"]),
                "forced": place in forced,
                "match": (path.group(1) if path else "", change_lines(item["diff"])),
                "llm_label": DECISION_LABEL.get(row["decision"], ""),
                "item": item,
                "key": {
                    "source": "review sheet",
                    "sheet": row["sheet"],
                    "row": row["row"],
                    "run": row["run"],
                    "item_id": row["item_id"],
                    "kind": row["kind"],
                    "category": row["category"],
                    "decision": row["decision"],
                    "votes": row["votes"],
                    "rows": [[r["sheet"], r["row"], r["decision"]] for r, _ in group],
                    "tier": "reviewer",
                    "calibration": f"C{forced.index(place) + 1}" if place in forced else "",
                },
            }
        )
    return out


def stratum(change: dict) -> tuple[str, str, str]:
    return change["pool"], change["label"], change["group"]


def stratum_order(cell: tuple[str, str, str]) -> tuple:
    pool, label, group = cell
    return POOLS.index(pool), label, GROUPS.index(group)


def allocate(changes: list[dict], quotas: dict) -> dict[tuple, int]:
    """Items per stratum: each label's quota spread evenly over its method groups, never fewer
    than its calibration items nor more than its changes."""
    size = Counter(stratum(c) for c in changes)
    alloc = Counter(stratum(c) for c in changes if c["forced"])
    for (pool, label), quota in quotas.items():
        cells = sorted((s for s in size if s[:2] == (pool, label)), key=stratum_order)
        while sum(alloc[s] for s in cells) < quota:
            room = [s for s in cells if alloc[s] < size[s]]
            if not room:
                break
            alloc[min(room, key=lambda s: alloc[s])] += 1
    return alloc


def draw(changes: list[dict], alloc: dict, rng: random.Random) -> list[dict]:
    """The calibration changes and a random draw per stratum; a review edit already drawn from the
    diff audit is not drawn again."""
    picked, shown = [], set()
    for cell in sorted(alloc, key=stratum_order):
        members = sorted((c for c in changes if stratum(c) == cell), key=lambda c: c["id"])
        chosen = [c for c in members if c["forced"]]
        rest = [c for c in members if not c["forced"] and c["match"] not in shown]
        chosen += rng.sample(rest, max(0, min(len(rest), alloc[cell] - len(chosen))))
        picked += chosen
        shown |= {c["match"] for c in chosen if c["pool"] == "diff audit"}
    return picked


def build(
    edits: list[dict],
    reviewed: list[dict],
    forced_audit: list[str],
    forced_review: list[tuple[str, int]],
    quotas: dict = QUOTAS,
    seed: int = SEED,
) -> tuple[list[dict], dict]:
    """(the items in their shuffled order, the key)."""
    changes = audit_changes(edits, forced_audit) + review_changes(reviewed, forced_review)
    rng = random.Random(seed)
    picked = draw(changes, allocate(changes, quotas), rng)
    rng.shuffle(picked)
    size = Counter(stratum(c) for c in changes)
    drawn = Counter(stratum(c) for c in picked)
    strata = [
        {
            "pool": s[0],
            "label": s[1],
            "group": s[2],
            "changes": size[s],
            "items": drawn[s],
            "weight": round(size[s] / drawn[s], 3) if drawn[s] else "",
        }
        for s in sorted(size, key=stratum_order)
    ]
    items = {
        str(n): {
            "stratum": " | ".join(stratum(c)),
            "weight": round(size[stratum(c)] / drawn[stratum(c)], 3),
            "llm_label": c["llm_label"],
            "group": c["group"],
            **c["key"],
        }
        for n, c in enumerate(picked, 1)
    }
    key = {
        "WARNING": WARNING,
        "seed": seed,
        "llm_label": "the diff audit's verdict (auditor no: fine), or the LLM reviewer's decision "
        "(accept: fine, unsure: debatable, reject: wrong)",
        "weight": "changes in the item's stratum / items drawn from it",
        "strata": strata,
        "items": items,
    }
    return [c["item"] for c in picked], key


def sections(item: dict) -> list[tuple[str, str, object]]:
    """(title, kind, content) blocks of an item; kind is text, code, diff or list."""
    out = [("Project", "text", item["project"]), ("File", "text", item["file"])]
    if item.get("kind"):
        out.append(("Kind", "text", item["kind"]))
    if item["code"]:
        out.append(("Code above the change" if item["diff"] else "Code", "code", item["code"]))
    if item.get("proposed"):
        out.append(("Proposed", "text", item["proposed"]))
    if item["diff"]:
        out.append(("Diff", "diff", item["diff"]))
    out.append((item["notes_title"], "list", item["notes"] or ["(none)"]))
    return out


def item_md(n: int, item: dict) -> str:
    lines = [f"## Item {n}", "", f"**Question:** {QUESTIONS[item['question']]}", ""]
    for title, kind, content in sections(item):
        if kind == "text":
            lines += [f"**{title}:** {content}", ""]
        elif kind == "list":
            lines += [f"**{title}:**", "", *(f"- {x}" for x in content), ""]
        else:
            fence = "```"
            while fence in content:
                fence += "`"
            lines += [f"**{title}:**", "", fence + ("diff" if kind == "diff" else ""), content]
            lines += [fence, ""]
    return "\n".join(lines)


def _inline(text: str, count: int = 0) -> str:
    """HTML text with `code` spans; count limits them (a list line quotes code after its name)."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text), count=count)


def _diff_html(diff: str) -> str:
    out = []
    for line in diff.splitlines():
        css = ""
        if line.startswith("@@"):
            css = "hunk"
        elif line[:1] in "+-" and not line.startswith(("+++", "---")):
            css = "add" if line[0] == "+" else "del"
        out.append(f'<span class="{css}">{html.escape(line)}</span>' if css else html.escape(line))
    return "\n".join(out)


def item_html(n: int, item: dict) -> str:
    parts = [f'<section class="item" id="item-{n}">', f"<h2>Item {n}</h2>"]
    parts.append(f'<p class="q"><b>Question:</b> {_inline(QUESTIONS[item["question"]])}</p>')
    for title, kind, content in sections(item):
        if kind == "text":
            parts.append(f"<p><b>{title}:</b> {_inline(content)}</p>")
        elif kind == "list":
            rows = "".join(f"<li>{_inline(x, 1)}</li>" for x in content)
            parts.append(f"<p><b>{html.escape(title)}:</b></p><ul>{rows}</ul>")
        else:
            body = _diff_html(content) if kind == "diff" else html.escape(content)
            parts.append(f"<p><b>{title}:</b></p><pre>{body}</pre>")
    return "\n".join([*parts, "</section>"])


def leaks(items: list[dict]) -> list[tuple[int, str]]:
    """(item, text) for each method, run or run-path name an item shows (code can hold such
    words legitimately: read the hits)."""
    return [
        (n, m.group(0)) for n, item in enumerate(items, 1) for m in LEAK.finditer(item_md(n, item))
    ]


def _filled(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8-sig", newline="") as f:
        return any((row.get("label") or "").strip() for row in csv.DictReader(f))


def write_packet(out: Path, items: list[dict], key: dict) -> None:
    sheets = [out / "rater_A.csv", out / "rater_B.csv"]
    for path in sheets:
        if _filled(path):
            raise SystemExit(f"{path} has labels; move it away before rebuilding")
    out.mkdir(parents=True, exist_ok=True)
    intro = (
        f"{len(items)} items. Give each a label in your sheet (wrong, debatable or fine) under "
        "rubric.md, with a confidence from 1 (a guess) to 3 (sure). Each item says its question."
    )
    md = [f"# Rating items\n\n{intro}\n", *(item_md(n, i) for n, i in enumerate(items, 1))]
    (out / "items.md").write_text("\n".join(md), encoding="utf-8")
    body = "\n".join(item_html(n, i) for n, i in enumerate(items, 1))
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Rating items</title><style>{CSS}</style></head><body>\n"
        f"<h1>Rating items</h1>\n<p>{_inline(intro)}</p>\n{body}\n</body></html>\n"
    )
    (out / "items.html").write_text(page, encoding="utf-8")
    for path in sheets:
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(SHEET_FIELDS)
            writer.writerows([n, "", "", "", ""] for n in range(1, len(items) + 1))
    (out / "key.json").write_text(json.dumps(key, indent=1) + "\n")
    (out / "README.md").write_text(README)
    (out / "rubric.md").write_text(RUBRIC)


def load(root: Path) -> tuple[list[dict], list[dict], list[str], list[tuple[str, int]]]:
    """(diff-audit edits, reviewed rows, the audit calibration edits, the reviewer calibration
    rows) of the checkout at root."""
    sys.path.insert(0, str(root / "scripts" / "experiments" / "v2"))
    import exp_diff_audit as audit_script  # root's copy, so the runs it collects are root's

    found, occurrences = audit_script.collect()
    audit = json.loads((audit_script.OUT / "audit.json").read_text())
    known = audit_script.checks()
    methods: dict[str, Counter] = {}
    runs: dict[str, set] = {}
    for r in occurrences:
        methods.setdefault(r["edit"], Counter())[r["method"]] += 1
        runs.setdefault(r["edit"], set()).add(f"{r['source']}/{r['method']}/{r['run']}")
    edits = []
    for edit_id, edit in sorted(found.items()):
        if edit_id not in audit:
            continue
        check = known.get(edit_id, {})
        edits.append(
            {
                "edit": edit_id,
                "same": json.dumps(audit_script._same(edit)),
                "project": edit["project"],
                "path": edit["path"],
                "diff": edit["diff"],
                "view": audit[edit_id]["view"],
                "answer": audit[edit_id]["answer"],
                "votes": [v["answer"] for v in audit[edit_id]["votes"]],
                "verdict": check.get("verdict", ""),
                "checked_by": check.get("checked_by", ""),
                "tier": audit_script.tier(check) if check else "",
                "methods": dict(methods[edit_id]),
                "runs": sorted(runs[edit_id]),
            }
        )
    reviewed, projects = [], {}
    cases = root / "results" / "raw" / "case_studies"
    for path in sorted(cases.glob("*/llm_review.json")):
        meta = json.loads((path.parent / "review_rows.json").read_text())
        rows = {r["n"]: r for r in meta["rows"]}
        for run in {r["run"] for r in meta["rows"]} - set(projects):
            projects[run] = json.loads((cases / run / "report.json").read_text())["repo_id"]
        for n, review in json.loads(path.read_text())["reviews"].items():
            row = rows[int(n)]
            reviewed.append(
                {
                    "sheet": path.parent.name,
                    "row": int(n),
                    "run": row["run"],
                    "project": projects[row["run"]],
                    "item_id": row["item_id"],
                    "kind": row["kind"],
                    "category": row["category"],
                    "decision": review["decision"],
                    "votes": review["votes"],
                    "view": review["view"],
                }
            )
    notes = root / ".notes" / "report"
    sheet, key = notes / "audit_calibration_sheet.md", notes / "calibration_key.json"
    pattern = r"^## \d+\. edit ([0-9a-f]{12})"
    forced_audit = re.findall(pattern, sheet.read_text(), re.M) if sheet.exists() else []
    calibration = json.loads(key.read_text()) if key.exists() else []
    return edits, reviewed, forced_audit, [(k["sheet"], k["row"]) for k in calibration]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", type=Path, default=OUT)
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout to read")
    args = parser.parse_args(argv)
    items, key = build(*load(args.root.resolve()))
    write_packet(args.out, items, key)
    for s in key["strata"]:
        print(f"{s['pool']} | {s['label']} | {s['group']}: {s['items']}/{s['changes']}")
    print(Counter(i["source"] for i in key["items"].values()))
    for n, text in leaks(items):
        print(f"check item {n}: {text}")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
