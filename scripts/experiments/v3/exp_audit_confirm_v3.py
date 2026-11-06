"""Targeted tests for the v3 audit's verdicts: v2's machinery (exp_audit_confirm.py: a short test
of the behavior a check says an edit changes, run in the run's own environment before and after
the edit; a test that passes before and fails after confirms it) on the v3 runs.

    python scripts/experiments/v3/exp_audit_confirm_v3.py run [--edits ID ...] [--raw DIR ...]
    python scripts/experiments/v3/exp_audit_confirm_v3.py record [--raw DIR ...]

Tests live in results/raw/diff_audit_v3/tests/<edit>/; results and checks go to the v3 audit's
files (exp_diff_audit_v3.py). An INJECT run's project opens from its injected clone, a REAL
run's from its held-out clone, as the run opened them.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_diff_audit_v3  # noqa: E402

CLONES = {"inject_v3": "data/raw/aidev/injected", "real_v3": "data/raw/aidev/heldout"}


def load(raws: list[Path]):
    """v2's confirm runner, reading and writing the v3 audit's files."""
    sys.modules["exp_diff_audit"] = exp_diff_audit_v3.load_v2(raws)
    path = HERE.parent / "v2" / "exp_audit_confirm.py"
    spec = importlib.util.spec_from_file_location("exp_audit_confirm_v3_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    v2_opened = module.opened
    module.opened = lambda project, report: opened(v2_opened, project, Path(report))
    return module


def opened(v2_opened, project: str, report: Path) -> tuple[str, dict]:
    """(workspace target, sandbox settings): the v3 runs' own clones for AIDev targets."""
    from cleansweep.core.config import load_config

    for folder, clones in CLONES.items():
        if project.startswith("aidev:") and folder in report.parts:
            sandbox = dict(load_config()["core"].get("sandbox") or {})
            return project, {**sandbox, "aidev_clones": clones}
    return v2_opened(project, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "record"])
    parser.add_argument("--edits", nargs="*")
    parser.add_argument("--raw", type=Path, action="append", help="a results/raw folder")
    args = parser.parse_args(argv)
    confirm = load(args.raw or [exp_diff_audit_v3.ROOT / "results" / "raw"])
    if args.what == "run":
        print(confirm.run(args.edits))
    else:
        print(f"{confirm.record()} checks recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
