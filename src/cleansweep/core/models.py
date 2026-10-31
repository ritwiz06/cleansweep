from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CATEGORIES = ["leftover_file", "dead_code", "duplicate", "wrapper",
              "unused_import", "unused_dependency", "security", "format", "other"]
ACTIONS = ["delete_file", "delete_unit", "remove_import", "remove_dependency",
           "replace_with", "apply_patch", "format", "report_only"]
LANES = ["safe", "suggest"]
EDIT_STATUS = ["kept", "repaired", "rolled_back", "skipped"]
METHODS = ["cleansweep", "guard_tests_only", "tools_only", "one_shot_llm",
           "no_ranker", "no_batching", "one_shot_retry", "agentic"]
POLICIES = ["now", "every_pr", "every_n", "daily", "adaptive"]

FEATURE_COLUMNS = [
    "kind_file", "kind_function", "kind_class",
    "n_refs_static", "n_callers", "reachable_from_entry", "imported_by_tests",
    "covered_lines_frac", "times_executed",
    "loc", "cyclomatic", "n_params", "is_wrapper",
    "name_pattern_score", "max_dup_similarity",
    "days_since_change", "commits_since_change", "written_by_agent",
    "dynamic_risk", "is_test_file",
]   # missing values are -1

STATS_KEYS = ["items_total", "items_safe", "items_kept", "items_repaired",
              "items_rolled_back", "lines_removed", "files_removed",
              "test_runs", "llm_calls", "prompt_tokens", "completion_tokens",
              "wall_seconds"]


@dataclass
class Task:                      # one SWE-bench Verified instance
    instance_id: str
    repo: str
    base_commit: str
    oracle_patch: str
    test_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    version: str


@dataclass
class AgentPatch:                # one agent-written patch (from PatchDiff)
    instance_id: str
    agent: str
    patch: str
    differs_from_oracle: bool | None = None       # PatchDiff label, None if unknown
    hidden_tests: list[str] = field(default_factory=list)   # never shown to the Guard


@dataclass
class RepoRef:                   # one AIDev repository we can run
    repo_id: str                 # "aidev:owner/name"
    url: str
    local_path: str | None = None
    head_sha: str | None = None
    test_cmd: str | None = None


@dataclass
class CommitEvent:
    sha: str
    timestamp: str               # ISO 8601, UTC
    is_agent: bool
    agent: str | None = None
    pr_number: int | None = None
    files: list[str] = field(default_factory=list)


@dataclass
class CodeUnit:
    path: str                    # repo-relative, forward slashes
    kind: str                    # "file" | "function" | "class" | "import" | "dependency"
    name: str | None = None      # qualified name inside the file, e.g. "Cart.total"
    start_line: int | None = None
    end_line: int | None = None

    @property
    def key(self) -> str:
        return self.path if not self.name else f"{self.path}::{self.name}"


@dataclass
class CleanupItem:
    item_id: str
    unit: CodeUnit
    category: str                # one of CATEGORIES
    action: str                  # one of ACTIONS
    lane: str                    # "safe" or "suggest"
    reason: str                  # one or two plain sentences for a human
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)   # "vulture", "graph", "minhash", "llm", ...
    keep_target: str | None = None   # duplicates: key of the copy we keep
    patch: str | None = None         # unified diff, for replace_with / apply_patch
    safe_score: float | None = None  # filled by the ranker
    llm_confidence: float | None = None


@dataclass
class CleanupPlan:
    repo_id: str
    created_at: str
    items: list[CleanupItem]


@dataclass
class RunResult:                 # result of one test run (not named Test* on purpose)
    ok: bool
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failed_ids: list[str] = field(default_factory=list)
    duration_s: float = 0.0


@dataclass
class DiffOutcome:
    same: bool
    n_cases: int = 0
    n_unstable: int = 0
    mismatches: list[str] = field(default_factory=list)


@dataclass
class EditResult:
    item_id: str
    status: str                  # one of EDIT_STATUS
    tests: RunResult | None = None
    ast_equal: bool | None = None
    diff_check: DiffOutcome | None = None
    diff: str = ""
    notes: str = ""


@dataclass
class SweepReport:
    repo_id: str
    method: str                  # one of METHODS
    policy: str                  # one of POLICIES
    seed: int
    started_at: str
    finished_at: str
    plan: CleanupPlan
    results: list[EditResult]
    stats: dict[str, Any] = field(default_factory=dict)   # keys from STATS_KEYS
