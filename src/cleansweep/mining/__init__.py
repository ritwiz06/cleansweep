from cleansweep.core.registry import use_stub

if use_stub("mining"):
    from .stub import build_taxonomy, find_removal_requests, mine_rules
else:
    from .comments import find_removal_requests
    from .rules import mine_rules
    from .taxonomy import build_taxonomy

__all__ = ["build_taxonomy", "find_removal_requests", "mine_rules"]
