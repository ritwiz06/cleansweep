"""Method labels for the v3 experiments: v2's (methods_v2.py) and the external baseline.

aider        Aider with the fixed cleanup instruction, the same model and endpoint
             (exp_external.py); its report has one kept edit per changed file, as the one-shot
             baseline's

plug(module) lets a v2 runner (exp_inject.py, exp_eval.py) run them as it runs its own: its
method choices, resolve and run_sweep become these.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "v2"))
sys.path.insert(0, str(HERE))

from methods_v2 import LABELS as V2_LABELS  # noqa: E402
from methods_v2 import resolve as resolve_v2  # noqa: E402

from cleansweep.workflow import run_sweep as run_sweep_v2  # noqa: E402

EXTERNAL = ["aider"]
LABELS = [*V2_LABELS, *EXTERNAL]


def resolve(label: str) -> tuple[str, str | None, dict]:
    """(method, v1 judge mode, core.agents overrides) for a method label."""
    if label in EXTERNAL:
        return label, None, {}
    return resolve_v2(label)


def run_sweep(target: str, cfg: dict, method: str = "cleansweep", seed: int = 0, on_event=None):
    """workflow.run_sweep, with the external baseline as one more method."""
    if method in EXTERNAL:
        from exp_external import run_external

        return run_external(target, cfg, seed)
    return run_sweep_v2(target, cfg, method, seed, on_event)


def plug(module) -> None:
    """Make a v2 runner module offer and run the v3 methods."""
    module.LABELS = LABELS
    module.resolve = resolve
    module.run_sweep = run_sweep
