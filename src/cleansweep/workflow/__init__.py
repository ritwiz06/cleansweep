from cleansweep.core.registry import use_stub

if use_stub("workflow"):
    from .stub import run_sweep
else:
    from .sweep import run_sweep

__all__ = ["run_sweep"]
