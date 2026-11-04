import { describe, expect, it } from "vitest";
import { auditBars, injectionBars, kindBars, methodName, parseCI, probeBars, ratio, records, reviewBars, scenarioBars, watchBars } from "./evaluation";

describe("evaluation tables", () => {
  it("reads rows by column and parses CIs and ratios", () => {
    expect(records({ columns: ["a", "b"], rows: [[1, "x"]] })).toEqual([{ a: 1, b: "x" }]);
    expect(parseCI("0.714 [0.600, 0.829]")).toEqual({ mean: 0.714, low: 0.6, high: 0.829 });
    expect(parseCI("--")).toBeNull();
    expect(ratio("50/70")).toEqual({ n: 50, d: 70 });
    expect(methodName("agentic-single_agent")).toBe("single agent");
    expect(methodName("something new")).toBe("something new");
  });

  it("charts the pooled injection rows, with the CI as offsets", () => {
    const rows = [
      { method: "agentic", seeds: "seed 1", "share per run (mean, 95% CI)": "0.5 [0.4, 0.6]", "traps removed": 0, runs: 10 },
      { method: "agentic", seeds: "pooled", "share per run (mean, 95% CI)": "0.7 [0.6, 0.9]", "traps removed": 1, runs: 20 },
    ];
    const [bar] = injectionBars(rows);
    expect(bar.method).toBe("team");
    expect(bar.share).toBe(0.7);
    expect(bar.ci[0]).toBeCloseTo(0.1);
    expect(bar.ci[1]).toBeCloseTo(0.2);
    expect(injectionBars(rows.slice(0, 1))[0].share).toBe(0.5); // one seed: no pooled row
  });

  it("splits wrong edits by tier per 100 kept edits, and counts kinds", () => {
    const audit = [
      { source: "injected", method: "agentic", kept_code_edits: 200, wrong: 4, wrong_confirmed: 3, wrong_reading: 1, debatable: 2 },
      { source: "aidev", method: "agentic", kept_code_edits: 10, wrong: 1, wrong_confirmed: 1, wrong_reading: 0, debatable: 0 },
    ];
    expect(auditBars(audit, "injected")).toEqual([{ method: "team", confirmed: 1.5, reading: 0.5, debatable: 1, kept: 200, wrong: 4 }]);
    const types = [
      { source: "injected", method: "agentic", verdict: "wrong", kind: "dependency", kept_code_edits: 2 },
      { source: "injected", method: "agentic", verdict: "debatable", kind: "public name", kept_code_edits: 5 },
    ];
    const [kinds] = kindBars(types, "injected");
    expect(kinds.dependency).toBe(2);
    expect(kinds["public name"]).toBe(0);
  });

  it("groups scenarios by Manager, keeps the reviewer's overall rows, averages watch policies", () => {
    const scenarios = [
      { scenario: "rollbacks", manager: "llm", accuracy: 0 },
      { scenario: "rollbacks", manager: "rules", accuracy: 1 },
    ];
    expect(scenarioBars(scenarios)).toEqual([{ scenario: "rollbacks", llm: 0, rules: 1 }]);
    const review = [
      { project: "p", mode: "all", category: "all", acceptance: 0.5, rows: 10 },
      { project: "p", mode: "safe", category: "all", acceptance: 0.2, rows: 4 },
    ];
    expect(reviewBars(review)).toEqual([{ project: "p", acceptance: 0.5, rows: 10 }]);
    const watch = [
      { policy: "watch", slop_debt_per_commit: 0.2, test_runs_est: 10 },
      { policy: "watch", slop_debt_per_commit: 0.4, test_runs_est: 30 },
    ];
    expect(watchBars(watch)).toEqual([{ policy: "watch", debt: 0.3, tests: 20, repos: 2 }]);
    const probes = [{ target_set: "swebench_t1", experiment: "patchdiff_recall", share_by_tests: 0, share_by_probes: 0.2, n: 3 }];
    expect(probeBars(probes)).toEqual([{ label: "SWE-bench T1: PatchDiff", tests: 0, probes: 0.2, n: 3 }]);
  });
});
