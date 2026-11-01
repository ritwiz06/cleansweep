from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

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


def _progress(event: dict) -> None:
    kind, p = event["kind"], event["payload"]
    if kind == "phase_change":
        back = " (step back)" if p.get("back") else ""
        print(f"-> {p['to']}{back}: {p['reason']}", file=sys.stderr)
    elif kind == "decision" and p.get("rule") in (
        "package_done",
        "approval",
        "budget",
        "baseline_failed",
    ):
        print(f"   {p['text']}", file=sys.stderr)
    elif kind == "lesson":
        print(f"   lesson {p['lesson_id']}: {p['reason']}", file=sys.stderr)
    elif kind == "log" and p.get("level") == "ERROR":
        print(f"   error in {event['agent']}: {p['message']}", file=sys.stderr)


def _ask_approval(blueprint: str) -> bool:
    print(f"\nThe plan is in {blueprint}.", file=sys.stderr)
    return input("Apply this plan? [y/N] ").strip().lower() in ("y", "yes")


def cmd_clean(args) -> int:
    import os

    from cleansweep.agents import clean_project
    from cleansweep.agents.budgets import parse_budget

    cfg = load_config()
    agents = cfg["core"].setdefault("agents", {})
    try:
        if args.budget:
            agents["budget"] = {**agents.get("budget", {}), **parse_budget(args.budget)}
    except ValueError as exc:
        print(f"cleansweep clean: {exc}", file=sys.stderr)
        return 2
    if args.approve_plan and not sys.stdin.isatty():
        print(
            "cleansweep clean: --approve-plan needs a terminal; use --dry-run to only plan",
            file=sys.stderr,
        )
        return 2
    if args.no_install:
        agents["install"] = "off"
    if args.model:
        os.environ["CLEANSWEEP_MODEL"] = args.model
        cfg["core"]["llm"]["model_env"] = "CLEANSWEEP_MODEL"
    try:
        result = clean_project(
            args.path,
            cfg,
            out=args.out,
            mode=args.mode,
            dry_run=args.dry_run,
            approve=_ask_approval if args.approve_plan else None,
            on_event=None if args.quiet else _progress,
            use_llm=not args.no_llm,
            test_args=shlex.split(args.test_args) if args.test_args else None,
            exclude=[e.rstrip("/") + "/" for e in args.exclude or []],
        )
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"cleansweep clean: {exc}", file=sys.stderr)
        return 1
    s = result["summary"]
    print(
        f"\nResult: {s['verdict']}. {s['applied']} edits applied; {s['lines_removed']} lines "
        f"and {s['files_removed']} files removed; {s['suggested']} suggestions."
    )
    if result["branch"]:
        print(f"Branch: {result['branch']} in {result['workspace']}")
    for path in result["files"]:
        print(f"  {path}")
    return 0 if s["verdict"] in ("everything runs", "nothing applied") else 1


def cmd_watch(args) -> int:
    from cleansweep.agents import clean_project, watch
    from cleansweep.agents.delivery import inside

    cfg = load_config()
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"cleansweep watch: {repo} is not a git repository", file=sys.stderr)
        return 2
    out = Path(args.out).expanduser().resolve() if args.out else repo.parent / f"{repo.name}-watch"
    if inside(out, repo):
        print("cleansweep watch: --out must be outside the repository", file=sys.stderr)
        return 2

    def clean(snapshot: str, run: str, test_runs: int | None) -> dict:
        agents = cfg["core"].setdefault("agents", {})
        if test_runs is not None:
            agents["budget"] = {**agents.get("budget", {}), "test_runs": test_runs}
        return clean_project(snapshot, cfg, out=run, mode=args.mode, use_llm=not args.no_llm)

    def show(entry: dict) -> None:
        print(f"{entry['commit'][:10]} {entry['decision']}: {entry['reason']}", flush=True)
        if entry.get("outcome"):
            print(f"  {entry['run']}: {entry['outcome']['verdict']}", flush=True)

    w = watch.Watch(str(repo), str(out), budget_tests=args.budget_tests)
    try:
        w.run(clean, interval=args.interval, polls=1 if args.once else args.polls, on_entry=show)
    except KeyboardInterrupt:
        pass
    print(f"watch log: {out / 'watch_log.jsonl'}")
    return 0


def cmd_studio(args) -> int:
    from cleansweep.core.config import REPO_ROOT

    # Studio lives in the repository's app/ folder, next to the package
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from app.studio.server import serve
    except ImportError as exc:
        print(f"cleansweep studio: {exc}; install requirements/rev.txt", file=sys.stderr)
        return 1
    return serve(args.port, args.runs, open_browser=not args.no_browser)


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
    p = sub.add_parser(
        "clean",
        help="clean a whole project with the agent team; the original folder is never changed",
        description=(
            "Copy a Python project into a scratch workspace and clean it in phases: onboard, "
            "baseline tests, audit, investigate, plan, then apply and verify one work package at a "
            "time. The result is a branch in the workspace (one commit per package), "
            "CLEANUP_REPORT.md and blueprint.md in the output folder. Nothing is applied to the "
            "original folder."
        ),
    )
    p.add_argument("path", help="the project folder to clean")
    p.add_argument(
        "--mode",
        choices=["safe", "thorough"],
        default=None,
        help="safe (default): deterministic edits only, anything uncertain is suggested; "
        "thorough: also LLM rewrites and more checks",
    )
    p.add_argument("--budget", help="caps for the whole run, e.g. llm=150,minutes=60,tests=80")
    p.add_argument(
        "--approve-plan", action="store_true", help="show blueprint.md and ask before applying"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="plan only: write blueprint.md and change nothing"
    )
    p.add_argument(
        "--out", help="output folder (default: <project>-cleanup-<time> next to the project)"
    )
    p.add_argument("--model", help="LLM model for the agents (default: VOYAGER_MODEL)")
    p.add_argument("--no-llm", action="store_true", help="run offline: the agents decide by rules")
    p.add_argument(
        "--exclude",
        action="append",
        metavar="FOLDER",
        help="a folder the cleanup leaves alone (repeatable), e.g. --exclude tests/fixtures",
    )
    p.add_argument(
        "--test-args",
        help="extra pytest arguments for the project's tests, e.g. --test-args \"-m 'not slow'\"",
    )
    p.add_argument(
        "--no-install",
        action="store_true",
        help="run the tests with this interpreter instead of installing the project into a venv",
    )
    p.add_argument("--quiet", action="store_true", help="print only the result")
    p.set_defaults(func=cmd_clean)
    p = sub.add_parser(
        "watch",
        help="follow a git repository's commits and clean a copy when the slop is worth it",
        description=(
            "Poll a git repository for new commits, estimate the slop with the static detectors, "
            "decide whether to clean now (each decision and its reason go to watch_log.jsonl), and "
            "run `clean` on a copy of the commit when it does. The repository is never changed."
        ),
    )
    p.add_argument("repo", help="the git repository to watch")
    p.add_argument("--budget-tests", type=int, default=0, help="test runs all cleans may use")
    p.add_argument("--interval", type=float, default=60, help="seconds between polls")
    p.add_argument("--once", action="store_true", help="poll once and exit")
    p.add_argument("--polls", type=int, help="stop after this many polls")
    p.add_argument("--out", help="watch folder (default: <repo>-watch next to the repository)")
    p.add_argument("--mode", choices=["safe", "thorough"], default=None)
    p.add_argument(
        "--no-llm", action="store_true", help="clean offline: the agents decide by rules"
    )
    p.set_defaults(func=cmd_watch)
    p = sub.add_parser(
        "studio",
        help="open CleanSweep Studio: launch, follow, replay and compare runs in the browser",
    )
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--runs", help="folder for runs started from Studio (default results/raw/studio)"
    )
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.set_defaults(func=cmd_studio)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
