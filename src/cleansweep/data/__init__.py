from cleansweep.core.registry import use_stub

if use_stub("data"):
    from .stub import load_agent_patches, load_history, load_removal_labels, load_repos, load_tasks
else:
    try:
        from .aidev import load_history, load_removal_labels, load_repos
        from .patchdiff import load_agent_patches
        from .swebench import load_tasks
    except ModuleNotFoundError as exc:
        # Real loaders not written yet (DA-01/02/05/06/07): use the stub until they are.
        # Remove this fallback once all three modules exist.
        if not (exc.name or "").startswith("cleansweep.data."):
            raise
        from .stub import (
            load_agent_patches,
            load_history,
            load_removal_labels,
            load_repos,
            load_tasks,
        )

__all__ = ["load_agent_patches", "load_history", "load_removal_labels", "load_repos", "load_tasks"]
