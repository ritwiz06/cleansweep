from __future__ import annotations

import argparse
import json
import sys

from cleansweep.core.config import load_config
from cleansweep.core.io import load_json, save_json
from cleansweep.core.models import METHODS, SweepReport


def _print_plan(plan) -> None:
    print(f"{'lane':<8} {'category':<18} {'action':<18} {'score':>5}  unit")
    for i in plan.items:
        score = f"{i.safe_score:.2f}" if i.safe_score is not None else "  -  "
        print(f"{i.lane:<8} {i.category:<18} {i.action:<18} {score:>5}  {i.unit.key}")
    print(
        f"\n{len(plan.items)} items, {sum(i.lane == 'safe' for i in plan.items)} in the safe lane"
    )


def _print_report(report: SweepReport) -> None:
    status = {r.item_id: r.status for r in report.results}
    print(f"{report.repo_id}  method={report.method}  seed={report.seed}")
    print(f"{'status':<12} {'category':<18} unit")
    for i in report.plan.items:
        print(f"{status.get(i.item_id, '-'):<12} {i.category:<18} {i.unit.key}")
    keys = [k for k in report.stats if k != "final_diff"]
    print("\n" + "  ".join(f"{k}={report.stats[k]}" for k in keys))


def cmd_sweep(args) -> int:
    from cleansweep.workflow import run_sweep

    cfg = load_config()
    report = run_sweep(args.target, cfg, method=args.method, seed=args.seed)
    if args.out:
        save_json(report, args.out)
    _print_report(report)
    if args.hidden:
        from cleansweep.eval import run_hidden_checks, summarize

        hidden = run_hidden_checks(args.target, report.stats.get("final_diff", ""), cfg)
        print("\nhidden checks:", json.dumps(summarize(report, hidden)))
    return 0


def cmd_plan(args) -> int:
    from cleansweep.analysis import build_graph, extract_features
    from cleansweep.ranking import load_ranker
    from cleansweep.reviewer import build_plan
    from cleansweep.sandbox import open_workspace

    cfg = load_config()
    with open_workspace(args.target, cfg["core"].get("sandbox")) as ws:
        graph = build_graph(ws.path)
        plan = build_plan(ws, graph, llm=None, use_llm=False)
        load_ranker(None).score(plan.items, extract_features(ws.path, graph))
    _print_plan(plan)
    return 0


def cmd_show(args) -> int:
    _print_report(load_json(SweepReport, args.report))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cleansweep")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sweep", help="clean up a target and verify every edit")
    p.add_argument("--target", required=True)
    p.add_argument("--method", default="cleansweep", choices=METHODS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out")
    p.add_argument("--hidden", action="store_true", help="also run hidden checks afterwards")
    p.set_defaults(func=cmd_sweep)
    p = sub.add_parser("plan", help="print the cleanup plan without applying anything")
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("show", help="print a saved sweep report")
    p.add_argument("report")
    p.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
