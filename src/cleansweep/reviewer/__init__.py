from cleansweep.core.registry import use_stub

if use_stub("reviewer"):
    from .stub import build_plan, judge_items, propose_fix, run_detectors
else:
    from .detectors import run_detectors
    from .judge import judge_items
    from .planner import build_plan
    from .repair import propose_fix

__all__ = ["build_plan", "judge_items", "propose_fix", "run_detectors"]
