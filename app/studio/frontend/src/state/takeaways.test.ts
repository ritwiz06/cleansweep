import { describe, expect, it } from "vitest";
import { injectionBars } from "./evaluation";
import { autonomyTakeaway, hypothesesTakeaway, injectionTakeaway, managerTakeaway, realAblationTakeaway, watchTakeaway } from "./takeaways";

describe("evaluation takeaways", () => {
  it("says the injection result in one sentence", () => {
    const bars = injectionBars([
      { method: "agentic", seeds: "pooled", "share per run (mean, 95% CI)": "0.814 [0.757, 0.857]", "traps removed": 0, runs: 10 },
      { method: "agentic-single_agent", seeds: "pooled", "share per run (mean, 95% CI)": "0.54 [0.4, 0.6]", "traps removed": 16, runs: 10 },
      { method: "one_shot_llm", seeds: "pooled", "share per run (mean, 95% CI)": "0.76 [0.7, 0.8]", "traps removed": 36, runs: 10 },
    ]);
    expect(injectionTakeaway(bars)).toBe("The team removed 81% of the planted slop and deleted no trap; one-shot deleted 36.");
    expect(injectionTakeaway([])).toBeNull();
  });

  it("reads the other tabs' rows", () => {
    const column = "wrong of kept code edits (confirmed by a test, check or rule)";
    expect(realAblationTakeaway([{ method: "team", [column]: "0 of 14 (0)" }, { method: "single_agent", [column]: "17 of 65 (12)" }])).toBe(
      "Wrong edits among the kept code edits on real projects: team 0 of 14, single agent 17 of 65.",
    );
    expect(managerTakeaway([{ scenario: "a", manager: "llm", accuracy: 1 }, { scenario: "a", manager: "rules", accuracy: 0 }])).toBe(
      "The LLM Manager got every run right in 1 of 1 scenarios, the rule-based one in 0.",
    );
    expect(watchTakeaway([{ policy: "watch", slop_debt_per_commit: 0.1, test_runs_est: 50 }, { policy: "none", slop_debt_per_commit: 14.56, test_runs_est: 0 }])).toBe(
      "Watch keeps the slop debt at 0.1 per commit for 50 test runs per repository; never cleaning leaves 14.56.",
    );
    expect(hypothesesTakeaway([{ hypothesis: "H1", result: "supported" }, { hypothesis: "H2", result: "not supported" }])).toBe("H1 supported, H2 not supported.");
    expect(autonomyTakeaway([{ pass: 1, runs: 30, completed: 27, rate: 0.9 }])).toBe("With no help, 27 of 30 runs on diverse repositories ended with a cleanup verdict (90%).");
    expect(autonomyTakeaway([])).toBeNull();
  });
});
