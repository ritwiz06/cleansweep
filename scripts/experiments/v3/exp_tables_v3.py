"""The v3 tables and the pre-registered hypotheses, from the v3 runs' records and the v3 audit.

    python scripts/experiments/v3/exp_tables_v3.py [--raw DIR ...]

Reads results/raw/{inject_v3,real_v3,autonomy}/ under each --raw folder (default: this
checkout's results/raw) and the v3 audit (exp_diff_audit_v3.py), and writes to
results/summary/v3/:
- injection.csv: per method on INJECT seed 4: runs planned, finished, timed out, not run by the
  freeze; recall (a timed-out run counts as removing nothing) with a bootstrap interval over
  repositories; traps removed and hidden changes on finished runs; LLM requests and minutes.
- real.csv: per method on REAL run 1: the same counts; projects with a held-out change and with a
  visible break (finished runs); lines removed (timed out: 0); requests and minutes.
- audit.csv: per set and method, kept code edits of finished runs and the wrong ones in two
  tiers (confirmed: a targeted test, the UI check or a rule; reading: LLM-judged) with a bootstrap
  interval over projects, and Fisher's exact test against the team.
- cost.csv; curve.csv: safety against yield on the curve's projects (the first five REAL), for
  every method that ran there, thorough and adaptive included.
- second_model.csv: the team and the single agent with each model on the same first five INJECT
  and REAL projects.
- sets.csv: the INJECT and REAL sets the runners settled on, each replacement with the repository
  it replaced and why (SlopBench lists its v3 repositories from it).
A rerun that replayed its first attempt's LLM cache takes that attempt's time and requests
(REPLAYED).
- hypotheses.csv: H1-H4 exactly as docs/preregistration_v3.md states them, each "supported",
  "not supported" or "not run by the freeze".
Every LLM-judged number is in a column that says so.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
import exp_autonomy  # noqa: E402
import exp_diff_audit_v3  # noqa: E402
from methods_v3 import LABELS, SECOND_MODEL  # noqa: E402

from cleansweep.eval.stats import mcnemar, wilcoxon  # noqa: E402

SUMMARY = ROOT / "results" / "summary" / "v3"
SPLIT = ROOT / "data" / "splits" / "v3_repos.json"
INJECT_METHODS = [
    "agentic",
    "agentic-no_resolver",
    "agentic-batch",
    "agentic-no_research",
    "agentic-single_agent",
    "aider",
    "cleansweep",
]
REAL_METHODS = [
    "agentic",
    "agentic-batch",
    "agentic-no_research",
    "agentic-single_agent",
    "aider",
    "cleansweep",
]
CURVE_METHODS = [*REAL_METHODS, "agentic-thorough", "agentic-adaptive"]
M2_METHODS = ["agentic", "agentic-m2", "agentic-single_agent", "agentic-single_agent-m2"]
KINDS = ("slop", "trap")
FIRST = 5  # the second model and the curve run on the first five of each settled set
# reruns whose check alone was spoiled replay the first attempt's LLM cache, so the cleanup is the
# same (final.diff identical); time, requests and tokens are the first attempt's
REPLAYED = {
    ("xgboosted__pandas-ta-classic", "agentic-no_research", 1): {
        "minutes": 71.15,
        "seconds": 4269.1,
        "llm_requests": 7,
        "prompt_tokens": 6586,
        "completion_tokens": 2996,
        "test_runs": 38,
    },
}
CONFIRMED = {"targeted test", "UI check", "rule: injection key", "rule: agent patch"}
N_BOOT, SEED = 10000, 572
NOT_RUN = "not run by the freeze"


def ratio_ci(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """(ratio, low, high): sum of numerators over sum of denominators, with a percentile
    bootstrap over the clusters (projects)."""
    if not pairs or not sum(d for _, d in pairs):
        return float("nan"), float("nan"), float("nan")
    rng, stats = random.Random(SEED), []
    for _ in range(N_BOOT):
        sample = [rng.choice(pairs) for _ in pairs]
        den = sum(d for _, d in sample)
        stats.append(sum(n for n, _ in sample) / den if den else 0.0)
    stats.sort()
    point = sum(n for n, _ in pairs) / sum(d for _, d in pairs)
    return point, stats[int(0.025 * N_BOOT)], stats[min(int(0.975 * N_BOOT), N_BOOT - 1)]


def fisher(a: int, n: int, b: int, m: int) -> float:
    from scipy.stats import fisher_exact

    return float(fisher_exact([[a, n - a], [b, m - b]])[1])


def planned_set(raws: list[Path], folder: str, split_names: list[str]) -> list[str]:
    """The set a runner settled on (its set.json, replacements in place) from the first --raw
    folder that has one, else the split's list."""
    for raw in raws:
        path = raw / folder / "set.json"
        if path.exists():
            return json.loads(path.read_text())["set"]
    return split_names


def sets_table(raws: list[Path], split: dict) -> list[dict]:
    """One row per repository of the settled INJECT and REAL sets (the split's lists before any
    run), with what each replacement replaced and why (local paths left out)."""
    out = []
    for name, folder in (("INJECT", "inject_v3"), ("REAL", "real_v3")):
        found = [raw / folder / "set.json" for raw in raws if (raw / folder / "set.json").exists()]
        data = json.loads(found[0].read_text()) if found else {}
        repos = data.get("set") or [r["full_name"] for r in split[name.lower()]]
        why = {r["by"]: r for r in data.get("replacements", [])}
        for repo in repos:
            r = why.get(repo, {})
            reason = r.get("reason", "")
            out.append(
                {
                    "set": name,
                    "repo": repo,
                    "replaces": r.get("replaced", ""),
                    "reason": reason.rpartition(": ")[2] if reason.startswith("/") else reason,
                }
            )
    return out


def autonomy_records(raws: list[Path]) -> list[dict]:
    """Every AUTONOMY result under any --raw folder."""
    return [
        json.loads(p.read_text())
        for raw in raws
        for p in sorted((raw / "autonomy").glob("*/pass*/result.json"))
    ]


def inject_records(raws: list[Path]) -> dict[tuple[str, str], dict]:
    """{(repository, method): stats} of every INJECT run with a record."""
    out = {}
    for raw in raws:
        for path in sorted((raw / "inject_v3").glob("*-s*/*.json")):
            if path.name == "key.json" or path.stem not in LABELS:
                continue
            out[(path.parent.name, path.stem)] = json.loads(path.read_text()).get("stats", {})
    return out


def real_records(raws: list[Path], run: int = 1) -> dict[tuple[str, str], dict]:
    """{(project, method): summary + held-out check} of every REAL run with a record."""
    out = {}
    for raw in raws:
        for folder in sorted((raw / "real_v3").glob(f"*/*-r{run}")):
            summary, held = folder / "summary.json", folder / "heldout.json"
            if not summary.exists():
                continue
            method = folder.name.rpartition("-r")[0]
            record = json.loads(summary.read_text())
            record.update(REPLAYED.get((folder.parent.name, method, run), {}))
            if held.exists():
                record["heldout"] = json.loads(held.read_text())
            out[(folder.parent.name, method)] = record
    return out


def wrong_by_run(raws: list[Path]) -> dict[tuple[str, str, str], dict]:
    """{(set, method, run): {"edits", "wrong", "wrong_confirmed", "debatable"}} from the v3
    audit's occurrences and checks; "wrong" includes the readings (LLM-judged)."""
    audit = exp_diff_audit_v3.load_v2(raws)
    if not (audit.OUT / "audit.json").exists():
        return {}
    _, rows = audit.collect()
    checks = audit.checks()
    out: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["source"], row["method"], row["run"])
        cell = out.setdefault(key, {"edits": 0, "wrong": 0, "wrong_confirmed": 0, "debatable": 0})
        cell["edits"] += 1
        check = checks.get(row["edit"])
        if check and check["verdict"] == "wrong":
            cell["wrong"] += 1
            cell["wrong_confirmed"] += check.get("checked_by") in CONFIRMED
        elif check and check["verdict"] == "debatable":
            cell["debatable"] += 1
    return out


def planted(records: dict, repo: str) -> int:
    """The slop planted in a repository (the same key for every method; 7 when no record has
    its plants)."""
    counts = [
        sum(p["kind"] == "slop" for p in stats.get("inject", {}).get("plants", []))
        for (r, _), stats in records.items()
        if r == repo
    ]
    return max(counts, default=0) or 7


def injection_table(records: dict, planned: list[str]) -> list[dict]:
    out = []
    for method in INJECT_METHODS:
        per_repo, traps, hidden, requests, minutes = [], 0, 0, [], []
        finished = timed = 0
        for repo in planned:
            stats = records.get((repo, method))
            if stats is None:
                continue
            plants = stats.get("inject", {}).get("plants", [])
            slop = [p for p in plants if p["kind"] == "slop"]
            if stats.get("timed_out"):
                timed += 1
                per_repo.append((0.0, float(planted(records, repo))))  # yield 0, still counted
                continue
            finished += 1
            per_repo.append((float(sum(p["removed"] for p in slop)), float(len(slop))))
            traps += sum(p["removed"] for p in plants if p["kind"] == "trap")
            hidden += bool(stats.get("hidden", {}).get("behavior_changed"))
            requests.append(stats.get("llm_calls") or 0)
            minutes.append(stats.get("minutes") or 0)
        recall, low, high = ratio_ci(per_repo)
        out.append(
            {
                "method": method,
                "planned": len(planned),
                "finished": finished,
                "timed_out": timed,
                NOT_RUN: len(planned) - finished - timed,
                "recall": _r(recall),
                "recall_ci_low": _r(low),
                "recall_ci_high": _r(high),
                "traps_removed (finished)": traps,
                "hidden_changed (finished)": hidden,
                "llm_requests_mean": _r(_mean(requests), 1),
                "minutes_mean": _r(_mean(minutes), 1),
            }
        )
    return out


def real_table(records: dict, planned: list[str]) -> list[dict]:
    out = []
    for method in REAL_METHODS:
        finished = timed = held = broken = lines = 0
        requests, minutes = [], []
        for project in planned:
            record = records.get((project, method))
            if record is None:
                continue
            if record.get("timed_out"):
                timed += 1
                continue
            finished += 1
            check = record.get("heldout", {})
            held += bool(check.get("behavior_changed"))
            broken += bool(check.get("visible_broken"))
            lines += record.get("lines_removed") or 0
            requests.append(record.get("llm_requests") or 0)
            minutes.append(record.get("minutes") or 0)
        out.append(
            {
                "method": method,
                "planned": len(planned),
                "finished": finished,
                "timed_out": timed,
                NOT_RUN: len(planned) - finished - timed,
                "heldout_changed_projects (finished)": held,
                "visible_broken_projects (finished)": broken,
                "lines_removed (timed out: 0)": lines,
                "llm_requests_mean": _r(_mean(requests), 1),
                "minutes_mean": _r(_mean(minutes), 1),
            }
        )
    return out


def audit_table(cells: dict, finished: dict[str, set]) -> list[dict]:
    """Per set and method, on finished runs only; Fisher's exact test against the team."""
    out = []
    for source, methods in (("injected v3", INJECT_METHODS), ("real v3", REAL_METHODS)):
        team = _pool(cells, source, "agentic", finished)
        for method in methods:
            mine = _pool(cells, source, method, finished)
            share, low, high = ratio_ci([(c["wrong"], c["edits"]) for c in mine])
            conf, clow, chigh = ratio_ci([(c["wrong_confirmed"], c["edits"]) for c in mine])
            n, w, wc = (sum(c[k] for c in mine) for k in ("edits", "wrong", "wrong_confirmed"))
            tn, tw, twc = (sum(c[k] for c in team) for k in ("edits", "wrong", "wrong_confirmed"))
            vs_team = method != "agentic" and n and tn
            out.append(
                {
                    "set": source,
                    "method": method,
                    "runs": len(mine),
                    "kept_code_edits": n,
                    "wrong_all_tiers (incl. LLM-judged readings)": w,
                    "wrong_confirmed": wc,
                    "debatable (LLM-judged)": sum(c["debatable"] for c in mine),
                    "share_all_tiers": _r(share),
                    "share_ci_low": _r(low),
                    "share_ci_high": _r(high),
                    "share_confirmed": _r(conf),
                    "confirmed_ci_low": _r(clow),
                    "confirmed_ci_high": _r(chigh),
                    "fisher_p_vs_team_all": _r(fisher(w, n, tw, tn)) if vs_team else "",
                    "fisher_p_vs_team_confirmed": _r(fisher(wc, n, twc, tn)) if vs_team else "",
                }
            )
    return out


def cost_table(inject: dict, real: dict) -> list[dict]:
    """LLM requests, tokens and minutes per finished run, per set and method."""
    out = []
    for source, records, methods in (
        ("INJECT", inject, INJECT_METHODS),
        ("REAL", real, REAL_METHODS),
    ):
        for method in methods:
            mine = [r for (_, m), r in records.items() if m == method and not r.get("timed_out")]
            requests = [_requests(r) for r in mine]
            tokens = [
                (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0) for r in mine
            ]
            out.append(
                {
                    "set": source,
                    "method": method,
                    "finished_runs": len(mine),
                    "llm_requests_mean": _r(_mean(requests), 1),
                    "tokens_mean": _r(_mean(tokens), 0),
                    "minutes_mean": _r(_mean([r.get("minutes") or 0 for r in mine]), 1),
                }
            )
    return out


def curve_table(real: dict, cells: dict, planned: list[str]) -> list[dict]:
    """Safety against yield on REAL run 1, on the curve's projects: wrong kept code edits (two
    tiers) against lines removed, per method, finished runs."""
    out = []
    for method in CURVE_METHODS:
        done = [
            p for p in planned if (p, method) in real and not real[(p, method)].get("timed_out")
        ]
        mine = [cells.get(("real v3", method, f"{p}/r1"), {}) for p in done]
        out.append(
            {
                "method": method,
                "projects": len(planned),
                "finished": len(done),
                "lines_removed": sum(real[(p, method)].get("lines_removed") or 0 for p in done),
                **_wrong(mine),
            }
        )
    return out


def second_model_table(inject: dict, real: dict, cells: dict, inject5: list, real5: list) -> list:
    """The team and the single agent with each model on the same five projects of each set;
    removal and safety on finished runs."""
    out = []
    for source, records, planned, run in (
        ("injected v3", inject, inject5, "{}"),
        ("real v3", real, real5, "{}/r1"),
    ):
        for method in M2_METHODS:
            ran = [x for x in planned if (x, method) in records]
            done = [records[(x, method)] for x in ran if not records[(x, method)].get("timed_out")]
            plants = [p for r in done for p in r.get("inject", {}).get("plants", [])]
            slop, traps = (sum(p["removed"] for p in plants if p["kind"] == k) for k in KINDS)
            mine = [cells.get((source, method, run.format(x)), {}) for x in ran]
            out.append(
                {
                    "set": source,
                    "method": method,
                    "model": SECOND_MODEL if method.endswith("-m2") else "first",
                    "planned": len(planned),
                    "finished": len(done),
                    "timed_out": len(ran) - len(done),
                    NOT_RUN: len(planned) - len(ran),
                    "slop_removed (INJECT)": slop if source == "injected v3" else "",
                    "traps_removed (INJECT)": traps if source == "injected v3" else "",
                    "lines_removed": sum(r.get("lines_removed") or 0 for r in done),
                    "behavior_changes": sum(changed(r) for r in done),
                    **_wrong(mine),
                    "llm_requests_mean": _r(_mean([_requests(r) for r in done]), 1),
                    "minutes_mean": _r(_mean([r.get("minutes") or 0 for r in done]), 1),
                }
            )
    return out


def _wrong(cells: list[dict]) -> dict:
    return {
        "kept_code_edits": sum(c.get("edits", 0) for c in cells),
        "wrong_all_tiers (incl. LLM-judged readings)": sum(c.get("wrong", 0) for c in cells),
        "wrong_confirmed": sum(c.get("wrong_confirmed", 0) for c in cells),
    }


def _requests(record: dict) -> int:
    return record.get("llm_calls") or record.get("llm_requests") or 0


def _pool(cells: dict, source: str, method: str, finished: dict[str, set]) -> list[dict]:
    return [
        c
        for (s, m, run), c in cells.items()
        if s == source and m == method and run in finished.get(f"{source}|{method}", set())
    ]


def finished_runs(inject: dict, real: dict) -> dict[str, set]:
    """The audit's run ids of the finished runs, per set and method."""
    out: dict[str, set] = {}
    for (repo, method), stats in inject.items():
        if not stats.get("timed_out"):
            out.setdefault(f"injected v3|{method}", set()).add(repo)
    for (project, method), record in real.items():
        if not record.get("timed_out"):
            out.setdefault(f"real v3|{method}", set()).add(f"{project}/r1")
    return out


def hypotheses(cells: dict, finished: dict, inject: dict, real: dict, autonomy: list) -> list:
    """H1-H4 as pre-registered; a hypothesis whose runs did not happen is not run by the freeze."""
    out = []

    def pooled(source, method):
        mine = _pool(cells, source, method, finished)
        return [sum(c[k] for c in mine) for k in ("edits", "wrong", "wrong_confirmed")]

    # H1
    tn, tw, twc = pooled("real v3", "agentic")
    an, aw, awc = pooled("real v3", "aider")
    both = [p for (p, m) in real if m == "agentic" and (p, "aider") in real]
    both = [p for p in both if not real[(p, "agentic")].get("timed_out")]
    both = [p for p in both if not real[(p, "aider")].get("timed_out")]
    if not (tn and an and both):
        out.append(_h("H1", NOT_RUN))
    else:
        p_all, p_conf = fisher(tw, tn, aw, an), fisher(twc, tn, awc, an)
        team_h = {
            p: bool(real[(p, "agentic")].get("heldout", {}).get("behavior_changed")) for p in both
        }
        aider_h = {
            p: bool(real[(p, "aider")].get("heldout", {}).get("behavior_changed")) for p in both
        }
        b = sum(team_h[p] and not aider_h[p] for p in both)
        c = sum(aider_h[p] and not team_h[p] for p in both)
        p_held = mcnemar(b, c)
        ok = (
            twc / tn < awc / an
            and p_conf < 0.05
            and tw / tn < aw / an
            and p_all < 0.05
            and sum(team_h.values()) < sum(aider_h.values())
            and p_held < 0.05
        )
        detail = (
            f"confirmed {twc}/{tn} vs {awc}/{an} (Fisher p={p_conf:.4f}); all tiers "
            f"{tw}/{tn} vs {aw}/{an} (p={p_all:.4f}); held-out changes "
            f"{sum(team_h.values())} vs {sum(aider_h.values())} of {len(both)} projects "
            f"(McNemar p={p_held:.4f})"
        )
        out.append(_h("H1", "supported" if ok else "not supported", detail))
    # H2
    repos = [r for (r, m) in inject if m == "agentic" and (r, "agentic-no_resolver") in inject]
    repos = [r for r in repos if not inject[(r, "agentic")].get("timed_out")]
    repos = [r for r in repos if not inject[(r, "agentic-no_resolver")].get("timed_out")]
    if not repos:
        out.append(_h("H2", NOT_RUN))
    else:

        def per_repo(method, key):
            return [cells.get(("injected v3", method, r), {}).get(key, 0) for r in repos]

        with_r, without = per_repo("agentic", "wrong"), per_repo("agentic-no_resolver", "wrong")
        conf_w, conf_wo = (
            per_repo("agentic", "wrong_confirmed"),
            per_repo("agentic-no_resolver", "wrong_confirmed"),
        )
        p = wilcoxon(with_r, without)[1]
        ok = sum(with_r) < sum(without) and p < 0.05 and sum(conf_w) <= sum(conf_wo)
        detail = (
            f"wrong (all tiers) {sum(with_r)} with vs {sum(without)} without over "
            f"{len(repos)} repositories (Wilcoxon p={p:.4f}); confirmed {sum(conf_w)} vs "
            f"{sum(conf_wo)}"
        )
        out.append(_h("H2", "supported" if ok else "not supported", detail))
    # H3
    pairs, team_w, batch_w, team_c, batch_c = [], [], [], [], []
    for records, source, keyfmt in ((inject, "injected v3", "{}"), (real, "real v3", "{}/r1")):
        for (x, m), rec in records.items():
            other = records.get((x, "agentic"))
            if (
                m != "agentic-batch"
                or other is None
                or rec.get("timed_out")
                or other.get("timed_out")
            ):
                continue
            reqs = (
                rec.get("llm_calls") or rec.get("llm_requests") or 0,
                other.get("llm_calls") or other.get("llm_requests") or 0,
            )
            pairs.append(reqs)
            run = keyfmt.format(x)
            batch_w.append(cells.get((source, "agentic-batch", run), {}).get("wrong", 0))
            team_w.append(cells.get((source, "agentic", run), {}).get("wrong", 0))
            batch_c.append(changed(rec))
            team_c.append(changed(other))
    if not pairs:
        out.append(_h("H3", NOT_RUN))
    else:
        ratio, low, high = ratio_ci(pairs)
        p_w = wilcoxon(batch_w, team_w)[1]
        b = sum(x and not y for x, y in zip(batch_c, team_c, strict=True))
        c = sum(y and not x for x, y in zip(batch_c, team_c, strict=True))
        p_c = mcnemar(b, c)
        worse = (sum(batch_w) > sum(team_w) and p_w < 0.05) or (
            sum(batch_c) > sum(team_c) and p_c < 0.05
        )
        ok = (
            ratio <= 0.60
            and sum(batch_w) <= sum(team_w)
            and sum(batch_c) <= sum(team_c)
            and not worse
        )
        detail = (
            f"request ratio {ratio:.3f} [{low:.3f}, {high:.3f}] over {len(pairs)} projects; "
            f"wrong {sum(batch_w)} vs {sum(team_w)} (Wilcoxon p={p_w:.4f}); behavior "
            f"changes {sum(batch_c)} vs {sum(team_c)} (McNemar p={p_c:.4f})"
        )
        out.append(_h("H3", "supported" if ok else "not supported", detail))
    # H4
    first = [r for r in autonomy if int(r["pass"]) == 1]
    if not first:
        out.append(_h("H4", NOT_RUN))
    else:
        done = sum(str(r["completed"]) == "True" for r in first)
        low, high = exp_autonomy.wilson(done, len(first))
        rate = done / len(first)
        detail = f"pass 1 completed {done} of {len(first)} ({rate:.3f}, Wilson [{low}, {high}])"
        out.append(_h("H4", "supported" if rate >= 0.90 else "not supported", detail))
    return out


def changed(record: dict) -> bool:
    """A behavior change in a run: the hidden test on INJECT, the held-out tests on REAL."""
    return bool((record.get("hidden") or record.get("heldout") or {}).get("behavior_changed"))


def _h(name: str, result: str, detail: str = "") -> dict:
    return {"hypothesis": name, "result": result, "evidence": detail}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def _r(x, digits: int = 3):
    return "" if x != x else round(x, digits)  # NaN -> blank


def write(name: str, rows: list[dict]) -> Path:
    SUMMARY.mkdir(parents=True, exist_ok=True)
    path = SUMMARY / name
    if rows:
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, action="append", help="a results/raw folder")
    args = parser.parse_args(argv)
    raws = args.raw or [ROOT / "results" / "raw"]
    split = json.loads(SPLIT.read_text())
    inject_names = planned_set(raws, "inject_v3", [r["full_name"] for r in split["inject"]])
    inject_planned = [n.replace("/", "__") + "-s4" for n in inject_names]
    real_names = planned_set(raws, "real_v3", [r["full_name"] for r in split["real"]])
    real_planned = [n.replace("/", "__") for n in real_names]
    inject, real = inject_records(raws), real_records(raws)
    cells, finished = wrong_by_run(raws), finished_runs(inject, real)
    autonomy = autonomy_records(raws)
    paths = [
        write("injection.csv", injection_table(inject, inject_planned)),
        write("real.csv", real_table(real, real_planned)),
        write("audit.csv", audit_table(cells, finished)),
        write("hypotheses.csv", hypotheses(cells, finished, inject, real, autonomy)),
        write("cost.csv", cost_table(inject, real)),
        write("curve.csv", curve_table(real, cells, real_planned[:FIRST])),
        write("sets.csv", sets_table(raws, split)),
        write(
            "second_model.csv",
            second_model_table(inject, real, cells, inject_planned[:FIRST], real_planned[:FIRST]),
        ),
    ]
    print(*paths, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
