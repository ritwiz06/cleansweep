from cleansweep.core.registry import use_stub

if use_stub("scheduler"):
    from .stub import apply_with_bisection, make_batches, should_sweep, simulate
else:
    from .batching import apply_with_bisection, make_batches
    from .policies import should_sweep
    from .replay import simulate

__all__ = ["apply_with_bisection", "make_batches", "should_sweep", "simulate"]
