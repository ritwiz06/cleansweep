"""Child process for a v1 sweep started from Studio: the dashboard's live runner, into --out."""

from __future__ import annotations

import argparse

from cleansweep.core.models import METHODS
from cleansweep.live import run_live


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one v1 sweep and record its events.")
    parser.add_argument("--target", required=True)
    parser.add_argument("--method", default="cleansweep", choices=METHODS)
    parser.add_argument("--judge-mode", choices=["gatekeeper", "advisory", "off"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report, run_dir = run_live(
        args.target, None, args.method, args.judge_mode, args.run_id, out_dir=args.out
    )
    print(f"{run_dir}  kept={report.stats['items_kept']} test_runs={report.stats['test_runs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
