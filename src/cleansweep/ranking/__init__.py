from cleansweep.core.registry import use_stub

if use_stub("ranking"):
    from .stub import Ranker, load_ranker
else:
    from .model import Ranker, load_ranker

__all__ = ["Ranker", "load_ranker"]
