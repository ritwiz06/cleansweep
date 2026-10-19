from __future__ import annotations

from cleansweep.core.models import RunResult

from .local import open_local
from .workspace import Workspace


class StubWorkspace(Workspace):
    """Real local copy, but tests always pass and nothing is executed."""

    def run_tests(self, test_paths: list[str] | None = None, timeout: int = 900) -> RunResult:
        self.test_runs += 1
        return RunResult(ok=True, passed=1)

    def coverage_json(self, test_paths: list[str] | None = None) -> str | None:
        return None


def open_workspace(target: str, cfg: dict | None = None) -> Workspace:
    ws = open_local(target, cfg)
    ws.__class__ = StubWorkspace
    return ws


__all__ = ["Workspace", "open_workspace"]
