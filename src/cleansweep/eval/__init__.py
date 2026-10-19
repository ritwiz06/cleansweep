from cleansweep.core.registry import use_stub

if use_stub("eval"):
    from .stub import one_shot_llm, run_hidden_checks, summarize, tools_only
else:
    from .baselines import one_shot_llm, tools_only
    from .hidden import run_hidden_checks
    from .metrics import summarize

__all__ = ["one_shot_llm", "run_hidden_checks", "summarize", "tools_only"]
