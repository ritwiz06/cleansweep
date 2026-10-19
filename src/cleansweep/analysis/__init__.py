from cleansweep.core.registry import use_stub

if use_stub("analysis"):
    from .stub import CodeGraph, build_graph, extract_features, find_duplicates
else:
    from .features import extract_features
    from .graph import CodeGraph, build_graph
    from .minhash import find_duplicates

__all__ = ["CodeGraph", "build_graph", "extract_features", "find_duplicates"]
