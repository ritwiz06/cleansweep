"""The LLM judge panel (the pre-registration's Deviation 9): three judges from model families
other than the agents', the auditor's and the second model's rate the blinded 100-item packet
under the raters' rubric. Reports their agreement with each other and with the recorded labels,
and their accuracy on the items whose verdict is confirmed.

    python scripts/experiments/v3/exp_judge_panel.py run [--packet DIR]
    python scripts/experiments/v3/exp_judge_panel.py table

run: each judge sees each item of items.md with rubric.md, in the packet's blinded view (no
method, no recorded verdict, the packet's shuffled order), 3 times (seeds 0, 1, 2, temperature
0.3). The votes and each item's recorded labels from key.json go to
results/summary/v3/judge_panel_votes.csv; the judges' reasons go to
results/raw/judge_panel_v3/reasons.json. table: reads only the votes file and writes
judge_panel.csv and judge_panel.md (reproduce_tables.sh runs it).

A judge's label is the label of at least 2 of its 3 votes, else "debatable"; the panel's label is
the label of at least 2 of the 3 judges, else "debatable". Agreement is unweighted over items: the
packet over-represents wrong labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v2"))

from exp_llm_review import cohen, fleiss  # noqa: E402

PACKET = ROOT / ".notes" / "report" / "human_rating"
RESULTS = Path(os.environ.get("CLEANSWEEP_RESULTS", ROOT / "results"))
VOTES = RESULTS / "summary" / "v3" / "judge_panel_votes.csv"
RAW = ROOT / "results" / "raw" / "judge_panel_v3"
JUDGES = ("gpt-oss-120b", "llama4-maverick-17b", "gemma4-31b-it")
LABELS = ("wrong", "debatable", "fine")
SEEDS = (0, 1, 2)
TEMPERATURE = 0.3
PARALLEL = 8  # requests in flight per judge
RESAMPLES = 2000
SEED = 572
VOTE_FIELDS = [
    "item", "source", "tier", "checked_by", "calibration", "ref", "recorded",
    "judge", "seed", "label",
]
FIELDS = ["measure", "who", "subset", "scale", "n", "value", "ci_low", "ci_high"]
SUBSETS = (
    "all",
    "diff audit",
    "diff audit (LLM-judged)",
    "diff audit (confirmed)",
    "review sheet",
    "calibration sheets",
)
SYSTEM = (
    "You rate one change to a software project under the rubric below. Judge only from what the "
    "item shows. Reply with JSON only: "
    '{"label": "wrong" | "debatable" | "fine", "reason": "<one sentence>"}.\n\n'
)


def read_items(path: Path) -> dict[str, str]:
    """item number -> the item's text as the raters saw it in items.md."""
    parts = re.split(r"^## Item (\d+)\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def majority(labels: list[str]) -> str:
    """The label given at least twice, else "debatable"."""
    label, count = Counter(labels).most_common(1)[0]
    return label if count >= 2 and label in LABELS else "debatable"


def vote(llm, rubric: str, text: str, seed: int) -> tuple[str, str]:
    """(label, reason) of one vote; an unusable reply is "none"."""
    messages = [{"role": "system", "content": SYSTEM + rubric}, {"role": "user", "content": text}]
    try:
        reply = llm.chat_json(messages, temperature=TEMPERATURE, seed=seed)
        label = str(reply.get("label", "")).lower().strip()
        reason = " ".join(str(reply.get("reason", "")).split())[:300]
    except Exception as exc:
        label, reason = "none", f"no usable reply ({type(exc).__name__})"
    return (label if label in LABELS else "none"), reason


def client(judge: str):
    from cleansweep.core.config import load_config
    from cleansweep.llm.client import LLMClient

    load_config()
    RAW.mkdir(parents=True, exist_ok=True)
    return LLMClient(
        model=judge,
        base_url=os.environ.get("VOYAGER_BASE_URL"),
        api_key=os.environ["VOYAGER_API_KEY"],
        cache_path=str(RAW / f"llm_cache_{judge}.sqlite"),
        max_retries=2,
        timeout_s=300,
    )


def recorded(item: dict) -> dict:
    """The key's fields the tables need, for one item."""
    ref = item.get("edit") or f"{item.get('sheet', '')}:{item.get('row', '')}"
    return {
        "source": item["source"],
        "tier": item["tier"],
        "checked_by": item.get("checked_by") or "",
        "calibration": item.get("calibration") or "",
        "ref": ref,
        "recorded": item["llm_label"],
    }


def run(packet: Path, judges=JUDGES, make_client=client) -> Path:
    items = read_items(packet / "items.md")
    key = json.loads((packet / "key.json").read_text())["items"]
    rubric = (packet / "rubric.md").read_text(encoding="utf-8")
    clients = {judge: make_client(judge) for judge in judges}

    def ask(job):
        judge, n, seed = job
        return job, vote(clients[judge], rubric, items[n], seed)

    # one pool per judge, so a slow judge does not hold up the others
    pools = {judge: ThreadPoolExecutor(PARALLEL) for judge in judges}
    order = sorted(items, key=int)
    futures = [pools[j].submit(ask, (j, n, s)) for j in judges for n in order for s in SEEDS]
    answers = dict(f.result() for f in futures)
    for pool in pools.values():
        pool.shutdown()
    rows, reasons = [], {}
    for (judge, n, seed), (label, reason) in answers.items():
        rows.append({"item": n, **recorded(key[n]), "judge": judge, "seed": seed, "label": label})
        reasons.setdefault(n, {}).setdefault(judge, []).append({"seed": seed, "reason": reason})
    VOTES.parent.mkdir(parents=True, exist_ok=True)
    with VOTES.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=VOTE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "reasons.json").write_text(json.dumps(reasons, indent=1))
    return VOTES


def load_votes(path: Path) -> tuple[dict, dict, list[str]]:
    """(item -> recorded fields, item -> judge -> label, judges in file order)."""
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    info, votes, judges = {}, {}, []
    for r in rows:
        info[r["item"]] = {k: r[k] for k in VOTE_FIELDS[1:7]}
        votes.setdefault(r["item"], {}).setdefault(r["judge"], []).append(r["label"])
        if r["judge"] not in judges:
            judges.append(r["judge"])
    labels = {n: {j: majority(v) for j, v in by.items()} for n, by in votes.items()}
    return info, labels, judges


def in_subset(info: dict, subset: str) -> bool:
    if subset == "all":
        return True
    if subset == "calibration sheets":
        return bool(info["calibration"])
    if subset == "review sheet":
        return info["source"] == "review sheet"
    if info["source"] != "diff audit":
        return False
    if subset == "diff audit (confirmed)":
        return info["tier"] == "confirmed"
    if subset == "diff audit (LLM-judged)":
        return info["tier"] != "confirmed"
    return True


def binary(label: str) -> str:
    return "wrong" if label == "wrong" else "not wrong"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centre - half, 3), round(centre + half, 3))


def bootstrap(stat, items: list, seed: int = SEED) -> tuple[float, float]:
    """95% bootstrap CI of stat over items (2000 resamples)."""
    rng = random.Random(seed)
    values = []
    for _ in range(RESAMPLES):
        value = stat([rng.choice(items) for _ in items])
        if value is not None and not math.isnan(value):
            values.append(value)
    if not values:
        return (math.nan, math.nan)
    values.sort()
    return (values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1])


def row(measure, who, subset, scale, n, value, ci=(None, None)) -> dict:
    low, high = ci
    return {
        "measure": measure, "who": who, "subset": subset, "scale": scale, "n": n,
        "value": value, "ci_low": "" if low is None else low,
        "ci_high": "" if high is None else high,
    }


def agreement_rows(info: dict, labels: dict, judges: list[str]) -> list[dict]:
    """The judges' agreement with each other and with the recorded labels."""
    raters = {j: {n: labels[n][j] for n in labels} for j in judges}
    raters["panel"] = {n: majority([labels[n][j] for j in judges]) for n in labels}
    rows = []
    for subset in SUBSETS:
        items = sorted((n for n in labels if in_subset(info[n], subset)), key=int)
        if not items:
            continue
        for scale, collapse in (("3 labels", str), ("wrong vs not wrong", binary)):
            cats = LABELS if scale == "3 labels" else ("wrong", "not wrong")

            def fl(pick, collapse=collapse, cats=cats):
                return fleiss([[collapse(raters[j][n]) for j in judges] for n in pick], cats)

            rows.append(row("Fleiss' kappa", "the three judges", subset, scale, len(items),
                            fl(items), bootstrap(fl, items)))
            pairs = [(a, b, a, b) for a, b in combinations(judges, 2)]
            pairs += [(j, "recorded", j, None) for j in [*judges, "panel"]]
            for a, b, x, y in pairs:
                def kappa(pick, x=x, y=y, collapse=collapse):
                    first = [collapse(raters[x][n]) for n in pick]
                    other = [collapse(raters[y][n] if y else info[n]["recorded"]) for n in pick]
                    return cohen(first, other)

                same = sum(
                    collapse(raters[x][n]) == collapse(raters[y][n] if y else info[n]["recorded"])
                    for n in items
                )
                who = f"{a} vs {b}"
                rows.append(row("raw agreement", who, subset, scale, len(items),
                                round(same / len(items), 3)))
                rows.append(row("Cohen's kappa", who, subset, scale, len(items), kappa(items),
                                bootstrap(kappa, items)))
    return rows


def validity_rows(info: dict, labels: dict, judges: list[str]) -> list[dict]:
    """Accuracy, sensitivity and specificity (wrong vs not wrong, Wilson 95%) on the confirmed
    verdicts, for each judge and the panel."""
    confirmed = sorted((n for n in labels if info[n]["tier"] == "confirmed"), key=int)
    rows = []
    for who in [*judges, "panel"]:
        said = {
            n: labels[n][who] if who != "panel" else majority([labels[n][j] for j in judges])
            for n in confirmed
        }
        truth = {n: binary(info[n]["recorded"]) for n in confirmed}
        right = [n for n in confirmed if binary(said[n]) == truth[n]]
        wrong_items = [n for n in confirmed if truth[n] == "wrong"]
        fine_items = [n for n in confirmed if truth[n] == "not wrong"]
        for measure, pool in (
            ("accuracy", confirmed),
            ("sensitivity", wrong_items),
            ("specificity", fine_items),
        ):
            k = sum(n in right for n in pool)
            value = round(k / len(pool), 3) if pool else ""
            rows.append(row(measure, who, "confirmed verdicts", "wrong vs not wrong", len(pool),
                            value, wilson(k, len(pool))))
    return rows


def reading_rows(info: dict, labels: dict, judges: list[str]) -> tuple[list[dict], list[dict]]:
    """The panel's agreement with the reading-tier verdicts, and the ones it overturns."""
    reading = sorted((n for n in labels if info[n]["tier"] == "reading"), key=int)
    panel = {n: majority([labels[n][j] for j in judges]) for n in reading}
    rows, overturned = [], []
    for scale, collapse in (("3 labels", str), ("wrong vs not wrong", binary)):
        same = [n for n in reading if collapse(panel[n]) == collapse(info[n]["recorded"])]
        rows.append(row("agrees with the reading", "panel", "diff audit (reading tier)", scale,
                        len(reading), len(same), wilson(len(same), len(reading))))
    for n in reading:
        if panel[n] != info[n]["recorded"]:
            overturned.append({
                "item": n, "ref": info[n]["ref"], "recorded": info[n]["recorded"],
                "panel": panel[n], **{j: labels[n][j] for j in judges},
            })
    return rows, overturned


def no_majority_rows(path: Path, labels: dict, judges: list[str]) -> list[dict]:
    """How often a judge's 3 votes, or the panel's 3 judges, had no majority."""
    with path.open(newline="") as f:
        votes = list(csv.DictReader(f))
    by = {}
    for r in votes:
        by.setdefault((r["judge"], r["item"]), []).append(r["label"])
    rows = []
    for judge in judges:
        split = sum(Counter(v).most_common(1)[0][1] < 2 for (j, _), v in by.items() if j == judge)
        unusable = sum(r["label"] == "none" for r in votes if r["judge"] == judge)
        rows.append(row("no majority of 3 votes", judge, "all", "3 labels", len(labels), split))
        rows.append(row("unusable votes", judge, "all", "3 labels", len(labels) * len(SEEDS),
                        unusable))
    split = sum(Counter(labels[n][j] for j in judges).most_common(1)[0][1] < 2 for n in labels)
    rows.append(row("no majority of 3 judges", "panel", "all", "3 labels", len(labels), split))
    return rows


def find(rows: list[dict], measure: str, who: str, subset: str, scale: str) -> dict | None:
    return next(
        (
            r for r in rows
            if (r["measure"], r["who"], r["subset"], r["scale"]) == (measure, who, subset, scale)
        ),
        None,
    )


def markdown(rows: list[dict], overturned: list[dict], judges: list[str], n_items: int) -> str:
    def cell(r):
        if r is None:
            return "n/a"
        if r["ci_low"] == "":
            return f"{r['value']} (n={r['n']})"
        return f"{r['value']} [{r['ci_low']}, {r['ci_high']}] (n={r['n']})"

    binary_scale = "wrong vs not wrong"
    lines = [
        "# LLM judge panel",
        "",
        f"Judges: {', '.join(f'`{j}`' for j in judges)}; {n_items} items of the blinded packet, "
        "3 votes each at temperature 0.3, majority per judge (else debatable) and per panel "
        "(else debatable). LLM-judged: no human checked these labels (pre-registration "
        "Deviation 9). Kappa CIs: 95% bootstrap over items; rates: Wilson 95%.",
        "",
        "## Agreement between the judges",
        "",
        "| Subset | Fleiss' kappa, 3 labels | Fleiss' kappa, wrong vs not wrong |",
        "|---|---|---|",
    ]
    for subset in SUBSETS:
        three = find(rows, "Fleiss' kappa", "the three judges", subset, "3 labels")
        two = find(rows, "Fleiss' kappa", "the three judges", subset, binary_scale)
        if three is None:
            continue
        lines.append(f"| {subset} | {cell(three)} | {cell(two)} |")
    lines += [
        "",
        "## Agreement with the recorded labels (Cohen's kappa)",
        "",
        "| Who | all, 3 labels | all, wrong vs not wrong | diff audit (LLM-judged), wrong vs not "
        "wrong | calibration sheets, 3 labels |",
        "|---|---|---|---|---|",
    ]
    for who in [*judges, "panel"]:
        cells = [
            find(rows, "Cohen's kappa", f"{who} vs recorded", s, sc)
            for s, sc in (
                ("all", "3 labels"),
                ("all", binary_scale),
                ("diff audit (LLM-judged)", binary_scale),
                ("calibration sheets", "3 labels"),
            )
        ]
        lines.append(f"| {who} | " + " | ".join(cell(c) for c in cells) + " |")
    lines += [
        "",
        "## Validity on the confirmed verdicts (wrong vs not wrong)",
        "",
        "| Who | Accuracy | Sensitivity | Specificity |",
        "|---|---|---|---|",
    ]
    for who in [*judges, "panel"]:
        cells = [
            find(rows, m, who, "confirmed verdicts", binary_scale)
            for m in ("accuracy", "sensitivity", "specificity")
        ]
        lines.append(f"| {who} | " + " | ".join(cell(c) for c in cells) + " |")
    agree = find(rows, "agrees with the reading", "panel", "diff audit (reading tier)", "3 labels")
    agree2 = find(rows, "agrees with the reading", "panel", "diff audit (reading tier)",
                  binary_scale)
    lines += [
        "",
        "## The reading tier",
        "",
        f"The panel agrees with {agree['value']} of {agree['n']} reading-tier verdicts on 3 labels "
        f"and {agree2['value']} of {agree2['n']} on wrong vs not wrong. Overturned (the panel's "
        "label differs from the recorded one):",
        "",
        "| Item | Edit | Recorded | Panel | " + " | ".join(judges) + " |",
        "|---|---|---|---|" + "---|" * len(judges),
    ]
    for o in overturned:
        lines.append(
            f"| {o['item']} | {o['ref']} | {o['recorded']} | {o['panel']} | "
            + " | ".join(o[j] for j in judges) + " |"
        )
    if not overturned:
        lines.append("| none | | | |" + " |" * len(judges))
    return "\n".join(lines) + "\n"


def table(votes: Path = VOTES) -> list[Path]:
    info, labels, judges = load_votes(votes)
    rows = agreement_rows(info, labels, judges)
    rows += validity_rows(info, labels, judges)
    reading, overturned = reading_rows(info, labels, judges)
    rows += reading
    rows += no_majority_rows(votes, labels, judges)
    out = votes.parent / "judge_panel.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    md = votes.parent / "judge_panel.md"
    md.write_text(markdown(rows, overturned, judges, len(labels)))
    return [out, md]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "table"])
    parser.add_argument("--packet", type=Path, default=PACKET)
    args = parser.parse_args(argv)
    if args.what == "run":
        print(run(args.packet))
    for path in table():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
