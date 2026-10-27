from cleansweep.core.registry import use_stub

from .workspace import Workspace

if use_stub("sandbox"):
    from .stub import open_workspace
else:
    from .local import open_local

    def open_workspace(target: str, cfg: dict | None = None) -> Workspace:
        """Open a workspace: a local path, "swebench:<instance_id>:<agent>" or
        "aidev:<owner>/<name>@<sha>" (both in Docker)."""
        if target.startswith("swebench:"):
            from .swebench_docker import open_swebench

            return open_swebench(target, cfg)
        if target.startswith("aidev:"):
            from .aidev_docker import open_aidev

            return open_aidev(target, cfg)
        return open_local(target, cfg)


__all__ = ["Workspace", "open_workspace"]
