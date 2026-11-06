"""The shared state of one agentic run: workspace, board, cache, budgets, lessons, results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cleansweep.analysis import build_graph
from cleansweep.core.models import CleanupItem, EditResult

from .board import MessageBoard
from .budgets import Budget, RunBudget
from .cache import ArtifactCache
from .events import EventLog
from .knowledge import KnowledgeBase
from .lessons import LessonStore
from .llm import AgentLLM
from .phases import PhaseMachine
from .secrets import Redactor, scan
from .tools import investigation_tools

ABLATIONS = {
    "no_research",
    "broadcast",
    "inline_artifacts",
    "no_lessons",
    "no_coverage",
    "single_agent",
}
MODES = {"safe", "thorough"}
INVESTIGATE = {"all", "adaptive", "none"}


@dataclass
class Package:
    """One work package: applied, checked and committed as a unit."""

    package_id: str
    goal: str
    items: list[str]
    files: list[str]
    risk: int = 1
    depends_on: list[str] = field(default_factory=list)
    verify: dict = field(default_factory=dict)
    rollback: str = ""
    status: str = "planned"  # planned, applied, kept, repaired, rolled_back, split, skipped
    start: str | None = None  # workspace checkpoint before the package
    commit: str | None = None  # delivery commit
    turns: int = 0  # repair turns used
    stage: str = "apply"  # apply, test, validate, fix, commit, done
    failure: dict = field(default_factory=dict)
    diff_id: str | None = None
    applied: list[str] = field(default_factory=list)  # items whose edit applied
    parent: str | None = None  # delivery commit this package's commit builds on


class Runtime:
    """Everything the agents share during one run."""

    def __init__(
        self,
        ws,
        cfg: dict,
        llm=None,
        out_dir: str | Path = ".",
        run_id: str = "agentic",
        on_event: Callable[[dict], None] | None = None,
        v1_hook: Callable[[str, dict], None] | None = None,
        mode: str | None = None,
        dry_run: bool = False,
        approve: Callable[[str], bool] | None = None,
        resume: bool = False,
    ):
        self.cfg = cfg
        self.acfg = cfg.get("core", {}).get("agents", {}) or {}
        self.mode = mode or self.acfg.get("mode", "safe")
        if self.mode not in MODES:
            raise ValueError(f"mode must be safe or thorough, got {self.mode!r}")
        self.manager_mode = self.acfg.get("manager", "llm")
        if self.manager_mode not in ("llm", "rules"):
            raise ValueError(f"manager must be llm or rules, got {self.manager_mode!r}")
        self.ablation = self.acfg.get("ablation")
        if self.ablation and self.ablation not in ABLATIONS:
            raise ValueError(f"unknown ablation {self.ablation!r}")
        if self.acfg.get("investigate", "all") not in INVESTIGATE:
            raise ValueError("investigate must be all, adaptive or none")
        self.ws = ws
        self.out = Path(out_dir).resolve()  # commands run in the workspace: never relative
        self.out.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self.approve = approve
        self.secrets = scan(ws.path)
        self.redact = Redactor(self.secrets["values"])
        self.log = EventLog(
            self.out / "events.jsonl", run_id, on_event, v1_hook, self.redact, append=resume
        )
        self.run_budget = RunBudget.from_cfg(self.acfg.get("budget"))
        self.llm = None
        if llm is not None:
            parallel = int(self.acfg.get("parallel_llm", 3))
            self.llm = AgentLLM(llm, self.redact, self.log, self.run_budget, parallel)
        self.board = MessageBoard(self.log, broadcast=self.ablation == "broadcast")
        self.cache = ArtifactCache(self.out / "cache", self.redact)
        self.phases = PhaseMachine(self.log)
        self.lessons = LessonStore(self.acfg.get("lessons_file"))
        self.kb = KnowledgeBase(self.acfg.get("knowledge_dir"))
        self.graph = build_graph(ws.path)
        self.tools = investigation_tools(self)
        self.usage: dict[str, dict] = {}
        self.node_stats: dict[str, list] = {}  # role -> [turns, seconds]
        # results of the phases
        self.brief: dict | None = None
        self.baseline: dict | None = None
        self.ui_base: dict | None = None  # Textual apps: the screens before any package
        self.items: dict[str, CleanupItem] = {}
        self.verdicts: dict[str, dict] = {}
        self.investigated = False
        self.packages: list[Package] = []
        self.current: int = 0
        self.results: dict[str, EditResult] = {}
        self.item_diffs: dict[str, str] = {}
        self.checks = 0
        self.audited = False
        self.planned = False
        self.plan_only = False  # the baseline could not run: deliver the plan as suggestions
        # the baseline could not run, and no_tests is "probes": apply only what probes cover
        self.untested = False
        self.error: str | None = None  # an agent failed: the run stopped on an error
        self.resumed: list[str] = []  # the phases this run was resumed at
        self.resumable = False  # `clean`: save a checkpoint at each safe point
        self.saved_at: tuple | None = None
        self.approved: bool | None = None
        self.reverting = False  # FINAL VERIFY found the suite worse: undo packages from the end
        self.final: dict | None = None
        self.delivery_tip: str | None = None
        self.branch: str | None = None
        self.workspace_info: dict = {}
        self.make_patches = False
        self.delivered: dict = {}
        self.summary: dict = {}
        self.files: list[str] = []
        self.environment: dict = {}
        self.turns = 0
        self.stopped: str | None = None
        # the LLM-guided Manager: its budget, the step-backs it took, and what it can undo
        self.manager_budget = Budget.from_cfg(self.acfg.get("manager_budget"))
        self.llm_back_steps = 0
        self.manager_llm = None  # the Manager's own LLM, when the other agents run without one
        self.budget_warned = False  # the Manager was asked once at 85% of a run cap
        self.revert_all = False  # FINAL VERIFY: undo every kept package, not just the last ones
        self.before_verdict: dict[str, tuple] = {}  # an item as the Investigator found it
        self.retry: set[str] = set()  # items to investigate again with twice the steps

    def budget(self, role: str) -> Budget:
        """A fresh budget for one instance of an agent."""
        return Budget.from_cfg(self.acfg.get(role))

    def record_usage(self, agent: str, budget: Budget) -> None:
        """Add one instance's use to the agent's totals."""
        role = agent.split("#")[0]
        used = budget.summary()
        total = self.usage.setdefault(
            role, {"instances": 0, "steps": 0, "llm_calls": 0, "seconds": 0.0}
        )
        total["instances"] += 1
        total["steps"] += used["steps"]
        total["llm_calls"] += used["llm_calls"]
        total["seconds"] = round(total["seconds"] + used["seconds"], 1)

    def agent_stats(self) -> dict[str, dict]:
        """Per agent role: turns, instances, tool steps, LLM requests and seconds."""
        out: dict[str, dict] = {}
        for role, (turns, seconds) in self.node_stats.items():
            out[role] = {
                "turns": turns,
                "instances": 1,
                "steps": 0,
                "llm_calls": 0,
                "seconds": round(seconds, 1),
            }
        names: dict[str, set] = {}
        for event in self.log.events:
            agent = event.get("agent") or ""
            role = agent.split("#")[0]
            if role in out:
                names.setdefault(role, set()).add(agent)
                out[role]["steps"] += event["kind"] == "tool_call"
        for role, found in names.items():
            out[role]["instances"] = max(1, len(found - {role}) or 1)
        for agent, n in (self.llm.by_agent if self.llm else {}).items():
            role = agent.split("#")[0]
            out.setdefault(
                role, {"turns": 0, "instances": 1, "steps": 0, "llm_calls": 0, "seconds": 0.0}
            )
            out[role]["llm_calls"] += n
        return out

    def artifact(self, kind: str, content) -> str:
        return self.cache.put(kind, content)

    def ref(self, art_id: str) -> str:
        """How a prompt or message mentions an artifact: its ID and a digest, or the whole text
        in the inline-artifacts ablation."""
        if self.ablation == "inline_artifacts":
            return f"{art_id}:\n{self.cache.text(art_id)}"
        return f"{art_id} ({self.cache.digest(art_id)})"

    def package(self) -> Package | None:
        return self.packages[self.current] if self.current < len(self.packages) else None

    def safe_items(self) -> list[CleanupItem]:
        return [i for i in self.items.values() if i.lane == "safe" and i.action != "report_only"]
