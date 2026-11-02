import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fold, itemsByStage, parseMismatch, phaseSeconds, type StudioEvent } from "./fold";

let n = 0;
function ev(kind: string, agent: string | null, payload: object, extra: Partial<StudioEvent> = {}): StudioEvent {
  n += 1;
  return { id: `e${n}`, t: n, kind, agent, phase: null, recipients: [], artifacts: [], payload, ...extra };
}

const msg = (agent: string, type: string, body: object, recipients: string[], artifacts: string[] = []) =>
  ev("message", agent, { msg_id: `m${n}`, type, body }, { recipients, artifacts });

function scenario(): StudioEvent[] {
  n = 0;
  return [
    ev("run_start", "manager", { repo_id: "local:proj", mode: "safe", budget: { test_runs: 50 } }),
    ev("phase_change", "manager", { from: null, to: "ONBOARD", reason: "start", back: false }),
    ev("phase_change", "manager", { from: "ONBOARD", to: "AUDIT", reason: "brief ready", back: false }),
    msg("auditor", "candidates", {
      items: [
        { item_id: "a", unit: "pkg/x.py::f", category: "dead_code", lane: "safe" },
        { item_id: "b", unit: "pkg/y.py", category: "leftover_file", lane: "safe" },
      ],
    }, ["manager", "investigator"]),
    msg("manager", "task", { goal: "Investigate", items: ["a", "b"] }, ["investigator"]),
    ev("tool_call", "investigator#1", { tool: "find_references", args: { name: "f" } }),
    ev("tool_result", "investigator#1", { tool: "find_references", result: "none", result_id: "R1" }),
    ev("llm_start", "investigator#1", { n: 1 }),
    ev("llm_end", "investigator#1", { n: 1, seconds: 0.5, ok: true }),
    msg("investigator#1", "verdict", {
      item_id: "a", decision: "safe", reason: "unused", evidence: [{ result: "R1" }], lessons_cited: ["L0"],
    }, ["manager", "planner"]),
    msg("investigator#2", "verdict", { item_id: "b", decision: "drop", reason: "used", evidence: [] }, ["manager"]),
    ev("phase_change", "manager", { from: "INVESTIGATE", to: "PLAN", reason: "1 safe", back: false }),
    msg("planner", "blueprint", { packages: ["P1"] }, ["manager", "engineer"], ["art:blueprint:00000001"]),
    ev("phase_change", "manager", { from: "PLAN", to: "EXECUTE", reason: "1 package", back: false }),
    msg("manager", "task", { goal: "Apply P1", package: "P1", kind: "apply", items: ["a"] }, ["engineer"]),
    msg("engineer", "package_applied", { package: "P1", applied: ["a"], not_applied: [] }, ["tester"], [
      "art:diff:00000002",
    ]),
    msg("tester", "test_result", { package: "P1", ok: true, new_failures: [] }, ["manager"]),
    msg("validator", "validation", {
      package: "P1", ok: true, coverage: 0.5,
      probes: { same: true, n_cases: 4, mismatches: [] }, checks: { ui: "not applicable" },
    }, ["manager"]),
    ev("check", "validator", { package: "P1", check: "probe coverage", coverage: 0.75, rounds: 2 }),
    ev("tool_result", "engineer", { tool: "commit", package: "P1", commit: "abc123" }),
    ev("decision", "manager", { rule: "package_done", text: "P1 kept", package: "P1", status: "kept" }),
    ev("phase_change", "manager", { from: "EXECUTE", to: "PLAN", reason: "re-plan", back: true }),
    ev("decision", "manager", { rule: "llm_manager", text: "go on", choice: "continue", options: ["continue", "stop"] }),
    ev("lesson", "fixer", { lesson_id: "L1", pattern: { category: "dead_code" }, reason: "probes failed" }),
    ev("budget", "explorer", { exhausted: "LLM-call budget (4) used up" }),
    msg("tester", "final_check", { ok: true, new_failures: [], passed: 5, baseline_passed: 5 }, ["manager"]),
    ev("run_end", "manager", { summary: { verdict: "everything runs", applied: 1 } }),
  ];
}

describe("fold", () => {
  it("tracks phases, step-backs and time per phase", () => {
    const s = fold(scenario());
    expect(s.phases.map((p) => p.phase)).toEqual(["ONBOARD", "AUDIT", "PLAN", "EXECUTE", "PLAN"]);
    expect(s.backSteps).toBe(1);
    expect(s.phase).toBe("PLAN");
    expect(phaseSeconds(s).PLAN).toBeGreaterThan(0);
  });

  it("moves items through the board and keeps each verdict's evidence chain", () => {
    const s = fold(scenario());
    expect(s.items.a.stage).toBe("kept");
    expect(s.items.a.pkg).toBe("P1");
    expect(s.items.a.history.map((h) => h.stage)).toEqual(["candidate", "investigating", "safe", "in_package", "kept"]);
    expect(s.items.a.chain.map((e) => e.kind)).toEqual(["tool_call", "tool_result"]);
    expect(s.items.a.verdict?.lessons).toEqual(["L0"]);
    expect(s.items.b.stage).toBe("dropped");
    expect(s.items.b.chain).toEqual([]);
    expect(itemsByStage(s).kept.map((i) => i.id)).toEqual(["a"]);
  });

  it("collects a package's diff, tests, probes, coverage, UI check and commit", () => {
    const p = fold(scenario()).packages.P1;
    expect(p.status).toBe("kept");
    expect(p.diffs).toEqual(["art:diff:00000002"]);
    expect(p.tests[0].ok).toBe(true);
    expect(p.validation.probes.n_cases).toBe(4);
    expect(p.coverage).toBe(0.75);
    expect(p.ui).toBe("not applicable");
    expect(p.commit).toBe("abc123");
  });

  it("counts agents' steps and LLM calls, test runs, decisions and the verdict", () => {
    const s = fold(scenario());
    expect(s.agents.investigator.steps).toBe(1);
    expect(s.agents.investigator.llmCalls).toBe(1);
    expect(s.agents.investigator.instances).toEqual(["investigator#1", "investigator#2"]);
    expect(s.llmCalls).toBe(1);
    expect(s.testRuns).toBe(2);
    expect(s.probes).toBe(4);
    expect(s.decisions.map((d) => d.rule)).toEqual(["package_done", "llm_manager"]);
    expect(s.lessons[0].id).toBe("L1");
    expect(s.budgetNotes[0].agent).toBe("explorer");
    expect(s.blueprint).toBe("art:blueprint:00000001");
    expect(s.finished && s.verdict).toBe("everything runs");
    expect(s.applied).toBe(1);
  });

  it("is a prefix fold: a partial log gives the state at that point", () => {
    const events = scenario();
    const s = fold(events.slice(0, 11));
    expect(s.items.a.stage).toBe("safe");
    expect(s.finished).toBe(false);
    expect(s.lastMessage?.type).toBe("verdict");
    expect(s.active).toBe("investigator");
  });

  it("parses probe mismatches into before and after", () => {
    expect(parseMismatch("a.py::f vs b.f [zero]: before '1', after '2'")).toEqual({
      target: "a.py::f vs b.f",
      case: "zero",
      before: "'1'",
      after: "'2'",
    });
    expect(parseMismatch("odd").target).toBe("odd");
  });

  it.each([
    "20261101_toy_clean_offline",
    "20261102_demo_feature_agentic",
    "20261101_manager_conflict_step_back",
    "20261101_skill_seekers_case_study",
  ])("folds the shipped recording %s to its report's numbers", (name) => {
    const dir = new URL(`../../../../../demo/replay/${name}/`, import.meta.url);
    const events = readFileSync(new URL("events.jsonl", dir), "utf8")
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    const report = JSON.parse(readFileSync(new URL("report.json", dir), "utf8"));
    const s = fold(events);
    expect(s.verdict).toBe(report.stats.agentic.verdict);
    // the events count test runs exactly only when run_end carries them (or no step ran tests
    // without a message, as in the toy run); the screen shows the report's count
    if (events.at(-1).payload.summary.test_runs !== undefined || name.includes("toy")) {
      expect(s.testRuns).toBe(report.stats.test_runs);
    }
    expect(s.candidates).toBe(report.stats.items_total);
    expect(s.agents.investigator.steps).toBe(report.stats.agentic.agents.investigator.steps);
    const statuses = (pkgs: { status: string }[]) => pkgs.map((p) => p.status).sort();
    expect(statuses(Object.values(s.packages))).toEqual(statuses(report.stats.agentic.packages));
  });
});
