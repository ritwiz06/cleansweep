from cleansweep.core.registry import use_stub

if use_stub("guard"):
    from .stub import Guard, apply_edit, verify
else:
    from .edits import apply_edit
    from .guard import Guard, verify

__all__ = ["Guard", "apply_edit", "verify"]
