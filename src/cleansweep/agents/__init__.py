"""CleanSweep v2: the agent team that cleans a whole project in phases (docs/agentic_design.md)."""

from cleansweep.core.registry import use_stub

if use_stub("agents"):
    from .stub import (
        ArtifactCache,
        EventLog,
        MessageBoard,
        PhaseMachine,
        Redactor,
        clean_project,
        run_agentic,
        scan_secrets,
    )
else:
    from .board import MessageBoard
    from .cache import ArtifactCache
    from .events import EventLog
    from .phases import PhaseMachine
    from .run import clean_project, run_agentic
    from .secrets import Redactor
    from .secrets import scan as scan_secrets

__all__ = [
    "ArtifactCache",
    "EventLog",
    "MessageBoard",
    "PhaseMachine",
    "Redactor",
    "clean_project",
    "run_agentic",
    "scan_secrets",
]
