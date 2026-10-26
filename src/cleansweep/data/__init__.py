from cleansweep.core.registry import use_stub

if use_stub("data"):
    from .stub import load_agent_patches, load_history, load_removal_labels, load_repos, load_tasks
else:
    from .patchdiff import load_agent_patches
    from .swebench import load_tasks

    try:
        from .aidev import load_history, load_removal_labels, load_repos
    except ModuleNotFoundError as exc:
        # AIDev loaders (DA-05/06/07) aren't written yet: use the stub until they are.
        if not (exc.name or "").startswith("cleansweep.data."):
            raise
        from .stub import load_history, load_removal_labels, load_repos

__all__ = ["load_agent_patches", "load_history", "load_removal_labels", "load_repos", "load_tasks"]
