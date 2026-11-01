"""Do the coverage-guided probes reach a project's duplicate rewrites? Before and after loading
scripts by path.

    python scripts/experiments/v2/exp_duplicate_probes.py TARGET --report REPORT.json
        [--out results/raw/duplicate_probes/NAME.json]

TARGET is a workspace target ("aidev:owner/name@sha" runs inside its network-less container).
For every duplicate in REPORT (a run's report.json), the detector's rewrite (replace_with) is
applied in a fresh checkpoint and probed with the Validator's coverage-guided probes twice:
"import" probes each target the way v2 did before (the harness imports the module by name), and
"by path" loads standalone scripts by path with their missing third-party modules stubbed. Both
variants use the same probe code (one LLM request per target, cached). The record has, per
duplicate: cases on its own target, whether the probes saw a behavior change, the scripts
loaded and the modules stubbed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cleansweep.agents import coverage_probes  # noqa: E402
from cleansweep.analysis import build_graph  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import load_json, save_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402
from cleansweep.guard import apply_edit  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402
from cleansweep.workflow.sweep import make_llm  # noqa: E402


@contextlib.contextmanager
def by_name_only():
    """Probe the way v2 did before scripts were loaded by path."""
    saved = coverage_probes.script_targets
    coverage_probes.script_targets = lambda repo_dir, targets: (targets, {})
    try:
        yield
    finally:
        coverage_probes.script_targets = saved


def probe_one(ws, item, graph, llm, guard_cfg) -> dict:
    start = ws.checkpoint(f"before {item.unit.key}")
    try:
        if not apply_edit(ws, item):
            return {"applied": False}
        row = {"applied": True}
        for variant in ("by_path", "import"):
            context = by_name_only() if variant == "import" else contextlib.nullcontext()
            with context:
                outcome, info = coverage_probes.probe_with_coverage(
                    ws, start, [item], graph, llm, guard_cfg
                )
            row[variant] = {
                "cases": info["cases_by_target"].get(item.unit.key, 0),
                "cases_by_target": info["cases_by_target"],
                "same": None if outcome is None else outcome.same,
                "mismatches": [] if outcome is None else outcome.mismatches[:3],
                "scripts": info.get("scripts", {}),
                "note": info["note"],
            }
        return row
    finally:
        ws.rollback(start)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", default=str(ROOT / "results" / "raw" / "duplicate_probes"))
    args = parser.parse_args(argv)
    cfg = load_config({"reviewer": {"scope": "repo"}})
    llm = make_llm(cfg["core"])
    report = load_json(SweepReport, args.report)
    items = [i for i in report.plan.items if i.category == "duplicate"]
    rows = []
    start = time.time()
    with open_workspace(args.target, cfg["core"].get("sandbox")) as ws:
        graph = build_graph(ws.path)
        for item in items:
            item.action = "replace_with"  # the detector's rewrite, whatever was decided later
            row = {
                "item": item.unit.key,
                "keep": item.keep_target,
                **probe_one(ws, item, graph, llm, cfg["core"]["guard"]),
            }
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in ("item", "applied")}), flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = args.target.split("/")[-1].split("@")[0]
    save_json(
        {"target": args.target, "seconds": round(time.time() - start, 1), "rows": rows},
        out / f"{name}.json",
    )
    for row in rows:
        cases = [row.get(v, {}).get("cases") for v in ("import", "by_path")]
        print(f"{row['item']}: applied={row['applied']} cases import/by path={cases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
