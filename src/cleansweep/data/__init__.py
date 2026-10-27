from cleansweep.core.registry import use_stub

if use_stub("data"):
    from .stub import load_agent_patches, load_history, load_removal_labels, load_repos, load_tasks
else:
    from .aidev import load_history, load_removal_labels, load_repos
    from .patchdiff import load_agent_patches
    from .swebench import load_tasks

__all__ = ["load_agent_patches", "load_history", "load_removal_labels", "load_repos", "load_tasks"]
