from cleansweep.core.registry import use_stub

from .workspace import Workspace

if use_stub("sandbox"):
    from .stub import open_workspace
else:
    from .local import open_local

    def open_workspace(target: str, cfg: dict | None = None) -> Workspace:
        """Open a workspace: a local path or "swebench:<instance_id>:<agent>" (in Docker)."""
        if target.startswith("swebench:"):
            from .swebench_docker import open_swebench

            return open_swebench(target, cfg)
        if target.startswith("aidev:"):
            raise NotImplementedError(f"AIDev Docker workspaces are not built yet: {target}")
        return open_local(target, cfg)


__all__ = ["Workspace", "open_workspace"]
