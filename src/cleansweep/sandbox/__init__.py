from cleansweep.core.registry import use_stub

from .workspace import Workspace

if use_stub("sandbox"):
    from .stub import open_workspace
else:
    from .local import open_local

    def open_workspace(target: str, cfg: dict | None = None) -> Workspace:
        """Open a workspace for a local path (Docker targets arrive with SA-07)."""
        if target.startswith(("swebench:", "aidev:")):
            raise NotImplementedError(f"Docker workspaces are not built yet: {target}")
        return open_local(target, cfg)


__all__ = ["Workspace", "open_workspace"]
