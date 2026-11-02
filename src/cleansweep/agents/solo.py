"""The single_agent ablation: one ReAct agent with every tool and one context does the whole
cleanup under the run's budget.

There is no Manager, phase machine, message board, work package or lesson. The agent lists the
detectors' candidates, investigates them with the Investigator's tools, applies edits, checks
them with the same tests and coverage-guided probes the team uses, and keeps or reverts each
one itself. The baseline before it starts and the full suite after it stops are measured for
the report, not enforced: whether it left the project worse is part of the result."""

from __future__ import annotations

import subprocess

from cleansweep.core.models import EditResult
from cleansweep.guard import apply_edit
from cleansweep.reviewer import build_plan
from cleansweep.sandbox.workspace import GIT_ID

from . import auditor, reporter, tester
from .budgets import Budget
from .coverage_probes import probe_with_coverage
from .explorer import project_facts
from .protocol import load_prompt, react
from .runtime import Package
from .tools import S, Tool, ToolSet, investigation_tools

NAME = "solo"
FINAL = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}
PAGE = 25
IDS = {"type": "array", "items": S, "minItems": 1}


class Solo:
    """The single agent's own tools and what it has applied, kept and reverted."""

    def __init__(self, rt):
        self.rt = rt
        self.applied: dict[str, str] = {}  # item -> workspace checkpoint before its edit
        self.kept: set[str] = set()
        self.reverted: set[str] = set()

    def find_candidates(self, category: str = "", offset: int = 0) -> str:
        rt = self.rt
        if not rt.items:
            plan = build_plan(rt.ws, rt.graph, llm=None, use_llm=False, cfg=rt.cfg)
            for item in [*plan.items, *auditor.line_items(rt, NAME)]:
                rt.items[item.item_id] = item
        items = [i for i in rt.items.values() if not category or i.category == category]
        page = items[offset : offset + PAGE]
        head = f"{len(items)} candidates" + (f" ({category})" if category else "")
        lines = [f"{head}; {offset + 1}-{offset + len(page)} shown"]
        lines += [
            f"{i.item_id} {i.category} {i.unit.key} action={i.action} detector_lane={i.lane}: "
            + "; ".join(i.evidence[:2])
            for i in page
        ]
        return "\n".join(lines)

    def apply(self, item_id: str) -> str:
        rt, item = self.rt, self.rt.items.get(item_id)
        if item is None:
            return f"no candidate {item_id}; call find_candidates first"
        if item_id in self.applied:
            return f"{item_id} is already applied"
        start = rt.ws.checkpoint(f"before {item_id}")
        if item.action == "report_only" or not apply_edit(rt.ws, item):
            return f"{item_id}: its edit ({item.action}) can't be applied"
        self.applied[item_id] = start
        self.reverted.discard(item_id)
        rt.item_diffs[item_id] = rt.ws.diff(start)
        return f"applied {item_id}:\n{rt.item_diffs[item_id]}"

    def run_tests(self, paths: list[str] | None = None) -> str:
        rt = self.rt
        if rt.run_budget.out_of_tests(rt.ws.test_runs):
            return "the run's test-run budget is used up"
        result, statuses = tester._run(rt, paths)
        new, removed = tester.compare(rt, result, statuses)
        if paths:  # a few files: only their tests count
            new, removed = [t for t in new if t in statuses or "crashed" in t], []
        out = f"{result.passed} passed, {result.failed} failed; new failures: {new[:10] or 'none'}"
        return out + (f"; tests removed with their files: {removed[:5]}" if removed else "")

    def run_probes(self, item_ids: list[str]) -> str:
        rt = self.rt
        live = [i for i in self.applied if i in item_ids]
        if not live:
            return "none of these items is applied"
        guard_cfg = rt.cfg.get("core", {}).get("guard", {})
        outcome, info = probe_with_coverage(
            rt.ws, self.applied[live[0]], [rt.items[i] for i in live], rt.graph, rt.llm, guard_cfg
        )
        if outcome is None:
            return f"no probes ran: {info.get('note', '')}"
        verdict = "same results" if outcome.same else "behavior changed"
        return (
            f"{outcome.n_cases} cases, {verdict}; cases per target {info['cases_by_target']}; "
            f"{outcome.mismatches[:5]}"
        )

    def revert(self, item_id: str) -> str:
        rt = self.rt
        if item_id not in self.applied:
            return f"{item_id} is not applied"
        patch = rt.item_diffs.get(item_id, "")
        if patch.strip():
            proc = subprocess.run(
                ["git", *GIT_ID, "apply", "-R", "--whitespace=nowarn", "-"],
                cwd=rt.ws.path,
                input=patch if patch.endswith("\n") else patch + "\n",
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                return f"{item_id} could not be reverted: {proc.stderr.strip()[:200]}"
        rt.ws.checkpoint(f"revert {item_id}")
        del self.applied[item_id]
        self.kept.discard(item_id)
        self.reverted.add(item_id)
        return f"reverted {item_id}"

    def keep(self, item_ids: list[str]) -> str:
        done = [i for i in item_ids if i in self.applied]
        self.kept.update(done)
        return f"kept {done}" if done else "none of these items is applied"

    def tools(self) -> ToolSet:
        own = [
            Tool(
                "find_candidates",
                "The detectors' cleanup candidates (id, category, unit, edit, lane, evidence), "
                f"{PAGE} at a time; optionally one category.",
                {"category": S, "offset": {"type": "integer", "minimum": 0}},
                [],
                self.find_candidates,
            ),
            Tool(
                "apply_edit",
                "Apply a candidate's edit to the workspace; returns its diff.",
                {"item_id": S},
                ["item_id"],
                self.apply,
            ),
            Tool(
                "run_tests",
                "Run the test suite (or the given test files) and compare with the baseline.",
                {"paths": {"type": "array", "items": S}},
                [],
                self.run_tests,
            ),
            Tool(
                "run_probes",
                "Coverage-guided differential probes: old vs new code on generated inputs, for "
                "applied items.",
                {"item_ids": IDS},
                ["item_ids"],
                self.run_probes,
            ),
            Tool("revert", "Undo an applied edit.", {"item_id": S}, ["item_id"], self.revert),
            Tool(
                "keep",
                "Keep applied edits you have checked.",
                {"item_ids": IDS},
                ["item_ids"],
                self.keep,
            ),
        ]
        return ToolSet([*own, *investigation_tools(self.rt).tools.values()])


def run(rt) -> None:
    """The whole run with one agent: baseline, the agent's loop, the final suite, the report."""
    rt.brief = project_facts(rt.ws.path, rt.graph)
    rt.phases.go("BASELINE", "the single agent's run: the baseline first")
    tester.baseline(rt)
    solo = Solo(rt)
    acfg = rt.acfg.get(NAME) or {}
    budget = Budget(
        int(acfg.get("steps", rt.run_budget.llm_calls or 150)),
        int(acfg.get("llm_calls", rt.run_budget.llm_calls or 150)),
        float(acfg.get("seconds", rt.run_budget.minutes * 60)),
    )
    base = rt.baseline or {}
    task = (
        f"Project facts: {rt.brief}\n\nBaseline: {base.get('passed')} tests pass in every run, "
        f"{base.get('failed')} already fail, {len(base.get('flaky', []))} are flaky. Clean the "
        "project up and leave it working: start with find_candidates."
    )
    if rt.llm is not None and rt.baseline.get("ok"):
        result = react(NAME, rt.llm, load_prompt(NAME), task, solo.tools(), FINAL, budget, rt.log)
        rt.stopped = None if result.stop == "final" else f"the agent stopped: {result.stop}"
    else:
        rt.stopped = "no LLM" if rt.llm is None else "the baseline tests could not run"
    rt.record_usage(NAME, budget)
    for n, iid in enumerate([*solo.applied, *sorted(solo.reverted)], 1):
        kept = iid in solo.applied
        note = "kept by the agent" if iid in solo.kept else "applied; the agent never kept it"
        status = "kept" if kept else "rolled_back"
        item = rt.items[iid]
        rt.packages.append(
            Package(
                f"S{n}",
                f"{item.category} {item.unit.key}",
                [iid],
                [item.unit.path],
                status=status,
                stage="done",
                applied=[iid],
            )
        )
        rt.results[iid] = EditResult(
            iid, status, diff=rt.item_diffs.get(iid, ""), notes=note if kept else "reverted"
        )
    if rt.packages:
        tester.final_check(rt)
    rt.phases.go("REPORT", "the single agent finished")
    reporter.run(rt, rt.workspace_info, patches=False)  # no packages to commit: the diff
    rt.phases.go("DONE", "report written")
