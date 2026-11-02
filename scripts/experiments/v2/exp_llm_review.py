"""An independent, blinded LLM review of the case-study review sheets and of the mined removal
requests. Its numbers are "LLM-reviewer acceptance (independent model, blinded)" and
"LLM-estimated precision": an LLM's judgment, not a human evaluation.

    python scripts/experiments/v2/exp_llm_review.py sheet NAME [--source-rev REV]
    python scripts/experiments/v2/exp_llm_review.py table
    python scripts/experiments/v2/exp_llm_review.py calibration [--n 20] [--seed 572]
    python scripts/experiments/v2/exp_llm_review.py kappa
    python scripts/experiments/v2/exp_llm_review.py mining

The reviewer is VOYAGER_MODEL_ALT, never the agents' model (VOYAGER_MODEL). For each row of a
review sheet (exp_review_sheet.py) it sees only the code around the change, the proposed change
or suggestion, and facts: the detectors' evidence, how often the name appears elsewhere in the
project, and the checks run on the change (tests, probes). Every applied and tried row is
reviewed; a sheet with more than --sample suggestions (default 40) gets a sample of them, taken
in turn from each category with a fixed seed. It never sees the agents' verdict,
reasons, lane, mode, or which agent produced the row. Rows go out in a shuffled order (fixed
seed); each is asked 3 times (seeds 0, 1, 2, temperature 0.3, reasoning off) and the majority
decides (no majority: unsure). The sheet's "LLM reviewer" columns are filled in and
results/raw/case_studies/NAME/llm_review.json keeps every vote. The source is the project at
the commit the run started from: the AIDev clone at the target's sha, or this repository at
--source-rev (or the record's "source_rev") for a local run.

table: results/summary/v2/llm_review_acceptance.csv from every reviewed sheet, with the votes'
agreement (all three the same; Fleiss' kappa).
calibration: .notes/report/calibration_sheet.md, 20 random rows (fixed seed) in the same blinded
view with an empty column for a person (the LLM decisions are in calibration_key.json, not on
the sheet). kappa: Cohen's kappa between that person and the LLM reviewer, once filled in.
mining: the same reviewer labels the 100 comments of .notes/mining_check.md (does the reviewer
ask to remove code?), blinded to the extraction model's label; results/summary/v2/
mining_llm_precision.csv gives the extraction's LLM-estimated precision and the agreement.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from exp_review_sheet import CASES, LABEL, write_sheet  # noqa: E402

from cleansweep.agents.protocol import REASONING_OFF  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import load_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402
from cleansweep.llm.client import get_client  # noqa: E402

SAMPLE = 40  # suggestions reviewed per sheet at most; every applied and tried row is reviewed
SEEDS = (0, 1, 2)
TEMPERATURE = 0.3
SHUFFLE_SEED = 572
PARALLEL = 3
NOTES = ROOT / ".notes"
SUMMARY = ROOT / "results" / "summary" / "v2"
CACHE = ROOT / "results" / "raw" / "llm_review" / "llm_cache.sqlite"
CATEGORY = {
    "dead_code": "unused code",
    "duplicate": "duplicated code",
    "wrapper": "a one-use wrapper",
    "leftover_file": "a leftover file",
    "unused_import": "an unused import",
    "unused_dependency": "an unused dependency",
    "security": "a security finding",
    "format": "formatting",
    "debug_leftover": "a debug leftover",
    "commented_code": "commented-out code",
    "todo_note": "a TODO note",
    "redundant_check": "a redundant check",
    "unused_variable": "an unused variable",
}
# evidence the agents wrote or that states a decision: never shown to the reviewer
HIDDEN = re.compile(
    r"^R\d+:|investigat|lesson|thorough|\bsafe\b|suggest|verdict|automatically|knowledge base"
    r"|so not |decid",
    re.IGNORECASE,
)
SYSTEM = (
    "You maintain a Python project. Someone proposes cleanup changes and suggestions for it. For "
    "each one you see the code, the proposed change and some facts. Decide as the maintainer "
    "whether you would accept it: accept (you would merge the change, or act on the "
    "suggestion), reject (you would not), or unsure (you would need more information). Judge "
    "the change on its merits: is it correct, does it keep behavior, is it worth having?"
)
QUESTION = (
    "As this project's maintainer, would you accept this change or suggestion? Reply with JSON "
    'only: {"decision": "accept" | "reject" | "unsure", "reason": "<one line>"}'
)
MINING_SYSTEM = (
    "You read code-review comments from pull requests. Decide whether the reviewer asks the "
    "author to remove code: delete code, a file, an import, a dependency, a duplicate or "
    "commented-out code."
)
MINING_QUESTION = (
    'Does this comment ask to remove code? Reply with JSON only: {"removal": "yes" | "no" | '
    '"unsure", "reason": "<one line>"}'
)


def reviewer():
    cfg = load_config()["core"]["llm"]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    return get_client({**cfg, "alt": True, "cache_path": str(CACHE)})


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def source(report: SweepReport, summary: dict, rev: str | None) -> tuple[Path, str]:
    """(git repository, commit) holding the project as the run found it."""
    if report.repo_id.startswith("aidev:"):
        full, _, sha = report.repo_id.removeprefix("aidev:").partition("@")
        clone = ROOT / load_config()["data"]["aidev"]["clones"] / full.replace("/", "__")
        return clone, sha or "HEAD"
    rev = rev or summary.get("source_rev")
    if not rev:
        raise SystemExit(f"{report.repo_id}: give --source-rev, the commit the run started from")
    return ROOT, rev


def _numbered(text: str, start: int, end: int, pad: int = 3, cap: int = 80) -> str:
    lines = text.splitlines()
    a, b = max(1, start - pad), min(len(lines), end + pad, start + cap)
    return "\n".join(f"{n:>5} {lines[n - 1]}" for n in range(a, b + 1))


def _context(repo: Path, rev: str, item) -> str:
    unit = item.unit
    text = _git(repo, "show", f"{rev}:{unit.path}")
    if not text:
        return "(the file could not be read)"
    if unit.start_line:
        return _numbered(text, unit.start_line, unit.end_line or unit.start_line)
    if unit.kind == "dependency" and unit.name:
        hits = [
            n
            for n, line in enumerate(text.splitlines(), 1)
            if re.search(rf"(?i)\b{re.escape(unit.name)}\b", line)
        ]
        if hits:
            return _numbered(text, hits[0], hits[0])
    return _numbered(text, 1, 40, pad=0)


def _name(item) -> str:
    unit = item.unit
    if unit.kind in ("file", "lines") or not unit.name:
        return Path(unit.path).stem
    return unit.name.split(".")[-1]


def _references(repo: Path, rev: str, item) -> str:
    name = _name(item)
    if len(name) < 3:
        return ""
    out = _git(repo, "grep", "-l", "-w", "-F", name, rev, "--", "*.py", "*.toml", "*.cfg", "*.md")
    files = sorted({line.split(":", 1)[1] for line in out.splitlines()} - {item.unit.path})
    if not files:
        return f"`{name}` appears in no other file of the project."
    shown = ", ".join(files[:6]) + (f" and {len(files) - 6} more" if len(files) > 6 else "")
    return f"`{name}` also appears in {len(files)} other file(s): {shown}."


def _proposal(item) -> str:
    unit, name = item.unit, item.unit.name or ""
    keep = (item.keep_target or "").replace("::", " ")
    action, cat = item.action, item.category
    if action == "delete_file" or (action == "report_only" and cat == "leftover_file"):
        return f"Delete the file `{unit.path}`."
    if action == "delete_unit" or (action == "report_only" and cat == "dead_code"):
        return f"Delete `{name}` from `{unit.path}`."
    if action == "remove_import" or cat == "unused_import":
        return f"Remove the import `{name}` from `{unit.path}`."
    if action == "remove_dependency" or cat == "unused_dependency":
        return f"Remove the dependency `{name}` from `{unit.path}`."
    if action == "replace_with" or cat in ("duplicate", "wrapper"):
        if cat == "wrapper":
            return f"Remove the wrapper `{name}` in `{unit.path}` and call what it wraps directly."
        return f"Remove `{name}` from `{unit.path}` and use `{keep}` instead."
    if action == "format" or cat == "format":
        return f"Reformat `{unit.path}` with the formatter (layout only)."
    if cat == "security":
        return f"Fix the security finding in `{unit.path}` (see the facts)."
    return f"Edit `{unit.path}` as in the diff below."


def view(item, result, repo: Path, rev: str, project: str) -> str:
    """The blinded text the reviewer sees for one row."""
    facts = [e for e in item.evidence if not HIDDEN.search(e)]
    refs = _references(repo, rev, item)
    if refs:
        facts.append(refs)
    if result is not None and result.status != "skipped":
        if result.tests is not None:
            facts.append(
                f"With the change applied, the tests ran: {result.tests.passed} passed, "
                f"{result.tests.failed} failed."
            )
        if result.diff_check is not None:
            d = result.diff_check
            facts.append(
                f"Differential probes (old vs new code on generated inputs): {d.n_cases} cases, "
                + ("same results." if d.same else "results changed.")
            )
        if result.notes and result.status == "rolled_back":
            facts.append("A check on the change failed: " + result.notes.splitlines()[0][:300])
    diff = (result.diff if result is not None and result.diff else "") or (item.patch or "")
    parts = [
        f"Project: {project}",
        f"Kind: {CATEGORY.get(item.category, item.category)}",
        f"Location: `{item.unit.path}`" + (f" (`{item.unit.name}`)" if item.unit.name else ""),
        "",
        "Code:",
        "```",
        _context(repo, rev, item),
        "```",
        "",
        f"Proposed: {_proposal(item)}",
    ]
    if diff:
        parts += ["", "Diff:", "```diff", diff[:4000], "```"]
    parts += ["", "Facts:", *(f"- {f}" for f in facts or ["(none)"])]
    return "\n".join(parts)


def _ask(llm, system: str, text: str, question: str, key: str, allowed: tuple) -> list[dict]:
    votes = []
    for seed in SEEDS:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{text}\n\n{question}"},
        ]
        try:
            reply = llm.chat_json(
                messages, temperature=TEMPERATURE, seed=seed, extra_body=REASONING_OFF
            )
            value = str(reply.get(key, "")).lower().strip()
            reason = " ".join(str(reply.get("reason", "")).split())[:300]
        except Exception as exc:  # an unusable reply counts as unsure
            value, reason = "unsure", f"no usable reply ({type(exc).__name__})"
        votes.append({"seed": seed, key: value if value in allowed else "unsure", "reason": reason})
    return votes


def majority(values: list[str]) -> str:
    value, count = Counter(values).most_common(1)[0]
    return value if count >= 2 else "unsure"


def fleiss(table: list[list[str]], labels: tuple) -> float | None:
    """Fleiss' kappa for items each rated by the same number of raters."""
    if not table:
        return None
    n = len(table[0])
    counts = [[row.count(c) for c in labels] for row in table]
    p_j = [sum(r[j] for r in counts) / (len(table) * n) for j in range(len(labels))]
    p_i = [(sum(c * c for c in r) - n) / (n * (n - 1)) for r in counts]
    p_bar, p_e = sum(p_i) / len(p_i), sum(p * p for p in p_j)
    return round((p_bar - p_e) / (1 - p_e), 3) if p_e < 1 else 1.0


def cohen(a: list[str], b: list[str]) -> float | None:
    if not a:
        return None
    labels = sorted(set(a) | set(b))
    p_o = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
    p_e = sum((a.count(c) / len(a)) * (b.count(c) / len(b)) for c in labels)
    return round((p_o - p_e) / (1 - p_e), 3) if p_e < 1 else 1.0


def _items(meta: dict):
    reports, summaries = {}, {}
    for run in {r["run"] for r in meta["rows"]}:
        reports[run] = load_json(SweepReport, CASES / run / "report.json")
        path = CASES / run / "summary.json"
        summaries[run] = json.loads(path.read_text()) if path.exists() else {}
    return reports, summaries


def pick_rows(rows: list[dict], limit: int = SAMPLE) -> list[dict]:
    """Every applied and tried row, and at most `limit` suggestions, taken in turn from each
    category (in a fixed shuffled order), so a long sheet's review stays affordable."""
    picked = [r for r in rows if r["kind"] != "suggestion"]
    suggestions = [r for r in rows if r["kind"] == "suggestion"]
    if len(suggestions) <= limit:
        return picked + suggestions
    rng = random.Random(SHUFFLE_SEED)
    by_category: dict[str, list[dict]] = {}
    for row in suggestions:
        by_category.setdefault(row["category"], []).append(row)
    queues = [rng.sample(group, len(group)) for _, group in sorted(by_category.items())]
    taken: list[dict] = []
    while len(taken) < limit:
        for queue in queues:
            if queue and len(taken) < limit:
                taken.append(queue.pop())
    return picked + sorted(taken, key=lambda r: r["n"])


def review_sheet(name: str, rev: str | None, limit: int = SAMPLE) -> Path:
    meta = json.loads((CASES / name / "review_rows.json").read_text())
    reports, summaries = _items(meta)
    jobs = []
    for row in pick_rows(meta["rows"], limit):
        report = reports[row["run"]]
        item = next(i for i in report.plan.items if i.item_id == row["item_id"])
        result = next((r for r in report.results if r.item_id == row["item_id"]), None)
        repo, commit = source(report, summaries[row["run"]], rev)
        jobs.append((row["n"], view(item, result, repo, commit, name)))
    random.Random(SHUFFLE_SEED).shuffle(jobs)
    llm = reviewer()
    allowed = ("accept", "reject", "unsure")

    def run(job):
        n, text = job
        return n, text, _ask(llm, SYSTEM, text, QUESTION, "decision", allowed)

    with ThreadPoolExecutor(PARALLEL) as pool:
        done = list(pool.map(run, jobs))
    reviews = {}
    for n, text, votes in sorted(done, key=lambda d: d[0]):
        decision = majority([v["decision"] for v in votes])
        reason = next((v["reason"] for v in votes if v["decision"] == decision), "")
        reviews[n] = {
            "decision": decision,
            "votes": [v["decision"] for v in votes],
            "reason": reason,
            "all": votes,
            "view": text,
        }
    out = CASES / name / "llm_review.json"
    record = {
        "label": LABEL,
        "model": llm.model,
        "seeds": SEEDS,
        "temperature": TEMPERATURE,
        "requests": llm.usage()["llm_calls"],
        "rows": len(meta["rows"]),
        "reviewed": len(reviews),
        "sample": f"every applied and tried row, at most {limit} suggestions (seed {SHUFFLE_SEED})",
        "reviews": {str(k): v for k, v in reviews.items()},
    }
    out.write_text(json.dumps(record, indent=1), encoding="utf-8")
    write_sheet(name, meta["safe"], meta["thorough"], reviews)
    return out


def table() -> Path:
    """Acceptance by project, mode, kind and category over every reviewed sheet."""
    rows, overall = [], {}
    for path in sorted(CASES.glob("*/llm_review.json")):
        name = path.parent.name
        meta = json.loads((path.parent / "review_rows.json").read_text())
        reviews = json.loads(path.read_text())["reviews"]
        groups: dict[tuple, list[dict]] = {}
        for row in meta["rows"]:
            review = reviews.get(str(row["n"]))
            if review:
                groups.setdefault((row["mode"], row["kind"], row["category"]), []).append(review)
                groups.setdefault((row["mode"], row["kind"], "all"), []).append(review)
                overall.setdefault(name, []).append(review)
        for (mode, kind, category), revs in sorted(groups.items()):
            rows.append(_line(name, mode, kind, category, revs))
    for name, revs in sorted(overall.items()):
        rows.append(_line(name, "all", "all", "all", revs))
    out = SUMMARY / "llm_review_acceptance.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return out


def _line(name: str, mode: str, kind: str, category: str, revs: list[dict]) -> dict:
    c = Counter(r["decision"] for r in revs)
    decided = c["accept"] + c["reject"]
    return {
        "measure": LABEL,
        "project": name,
        "mode": mode,
        "kind": kind,
        "category": category,
        "rows": len(revs),
        "accept": c["accept"],
        "reject": c["reject"],
        "unsure": c["unsure"],
        "acceptance": round(c["accept"] / decided, 3) if decided else "",
        "unanimous": round(sum(len(set(r["votes"])) == 1 for r in revs) / len(revs), 3),
        "fleiss_kappa": fleiss([r["votes"] for r in revs], ("accept", "reject", "unsure")),
    }


def calibration(n: int, seed: int) -> Path:
    pool = []
    for path in sorted(CASES.glob("*/llm_review.json")):
        for k, review in json.loads(path.read_text())["reviews"].items():
            pool.append((path.parent.name, int(k), review))
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    lines = [
        "# Calibration sheet: the LLM reviewer against a person",
        "",
        f"{len(picked)} rows drawn at random (seed {seed}) from the case-study review sheets, in",
        "the same blinded view the LLM reviewer saw. For each, write `accept`, `reject` or",
        "`unsure` after **Your decision** (would you, as the project's maintainer, accept this",
        "change or suggestion?). The LLM's decisions are in calibration_key.json, not here. Then:",
        "`python scripts/experiments/v2/exp_llm_review.py kappa`.",
        "",
    ]
    key = []
    for i, (name, row, review) in enumerate(picked, 1):
        lines += [f"## C{i}", "", review["view"], "", "**Your decision:** ", ""]
        key.append({"id": f"C{i}", "sheet": name, "row": row, "llm": review["decision"]})
    out = NOTES / "report" / "calibration_sheet.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    (out.parent / "calibration_key.json").write_text(json.dumps(key, indent=1))
    return out


def kappa() -> dict:
    sheet = (NOTES / "report" / "calibration_sheet.md").read_text(encoding="utf-8")
    key = json.loads((NOTES / "report" / "calibration_key.json").read_text())
    found = dict(re.findall(r"## (C\d+)\n.*?\*\*Your decision:\*\* *(\w*)", sheet, re.S))
    pairs = [(found.get(k["id"], "").lower(), k["llm"]) for k in key]
    pairs = [(h, m) for h, m in pairs if h in ("accept", "reject", "unsure")]
    out = {
        "labeled": len(pairs),
        "of": len(key),
        "agreement": round(sum(h == m for h, m in pairs) / len(pairs), 3) if pairs else None,
        "cohen_kappa": cohen([h for h, _ in pairs], [m for _, m in pairs]),
    }
    if not pairs:
        out["status"] = "not checked by a human: the calibration sheet has no decisions"
    return out


def _mining_items() -> list[dict]:
    text = (NOTES / "mining_check.md").read_text(encoding="utf-8")
    items = []
    for block in re.split(r"\n(?=## \d+\. )", text):
        head = re.match(r"## (\d+)\. .*? — `([^`]*)`", block)
        if not head:
            continue
        quote = "\n".join(ln[2:] for ln in block.splitlines() if ln.startswith("> "))
        llm = re.search(r"LLM: removal = (True|False)", block)
        human = re.search(r"\*\*Your label:\*\* *(yes|no)?", block)
        items.append(
            {
                "n": int(head.group(1)),
                "path": head.group(2),
                "comment": quote,
                "extracted": llm.group(1) == "True" if llm else None,
                "human": (human.group(1) or "") if human else "",
            }
        )
    return items


def mining() -> Path:
    items = _mining_items()
    llm = reviewer()
    jobs = [(i["n"], f"File: `{i['path']}`\n\nComment:\n> {i['comment']}") for i in items]
    random.Random(SHUFFLE_SEED).shuffle(jobs)

    def run(job):
        n, text = job
        return n, _ask(
            llm, MINING_SYSTEM, text, MINING_QUESTION, "removal", ("yes", "no", "unsure")
        )

    with ThreadPoolExecutor(PARALLEL) as pool:
        votes = dict(pool.map(run, jobs))
    for i in items:
        i["votes"] = [v["removal"] for v in votes[i["n"]]]
        i["reviewer"] = majority(i["votes"])
    flagged = [i for i in items if i["extracted"]]
    decided = [i for i in flagged if i["reviewer"] != "unsure"]
    reviewer_yes = [i for i in items if i["reviewer"] == "yes"]
    both = [i for i in items if i["reviewer"] != "unsure" and i["extracted"] is not None]
    row = {
        "measure": "LLM-estimated precision (independent model, blinded)",
        "sample": len(items),
        "extracted_removal": len(flagged),
        "reviewer_yes_of_extracted": sum(i["reviewer"] == "yes" for i in flagged),
        "reviewer_unsure_of_extracted": len(flagged) - len(decided),
        "precision": round(sum(i["reviewer"] == "yes" for i in decided) / len(decided), 3)
        if decided
        else "",
        "reviewer_yes": len(reviewer_yes),
        "recall_in_sample": round(
            sum(bool(i["extracted"]) for i in reviewer_yes) / len(reviewer_yes), 3
        )
        if reviewer_yes
        else "",
        "kappa_extraction_vs_reviewer": cohen(
            ["yes" if i["extracted"] else "no" for i in both], [i["reviewer"] for i in both]
        ),
        "unanimous": round(sum(len(set(i["votes"])) == 1 for i in items) / len(items), 3),
        "fleiss_kappa": fleiss([i["votes"] for i in items], ("yes", "no", "unsure")),
        "human_labeled": sum(bool(i["human"]) for i in items),
    }
    human = [i for i in items if i["human"] and i["reviewer"] != "unsure"]
    row["kappa_human_vs_reviewer"] = cohen(
        [i["human"] for i in human], [i["reviewer"] for i in human]
    )
    out = SUMMARY / "mining_llm_precision.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    (NOTES / "mining_llm_review.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["sheet", "table", "calibration", "kappa", "mining"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--source-rev")
    parser.add_argument("--sample", type=int, default=SAMPLE, help="suggestions per sheet")
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=SHUFFLE_SEED)
    args = parser.parse_args(argv)
    if args.what == "sheet":
        if not args.name:
            parser.error("sheet needs a case-study NAME")
        print(review_sheet(args.name, args.source_rev, args.sample))
    elif args.what == "table":
        print(table())
    elif args.what == "calibration":
        print(calibration(args.n, args.seed))
    elif args.what == "kappa":
        print(json.dumps(kappa()))
    else:
        print(mining())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
