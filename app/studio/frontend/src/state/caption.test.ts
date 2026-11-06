import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { captionFor, captionSteps, captionText, itemLabel } from "./caption";
import { fold, type StudioEvent } from "./fold";
import { afterSlides, nextDecisionStep } from "./present";
import { parseDiff } from "./diff";

function recording(name: string) {
  const base = new URL(`../../../../../demo/replay/${name}/`, import.meta.url);
  const events: StudioEvent[] = readFileSync(new URL("events.jsonl", base), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  return { events, report: JSON.parse(readFileSync(new URL("report.json", base), "utf8")) };
}

const ev = (kind: string, agent: string, payload: object, extra: Partial<StudioEvent> = {}): StudioEvent => ({
  id: "e1", t: 1, kind, agent, phase: null, recipients: [], artifacts: [], payload, ...extra,
});

describe("captions", () => {
  it("says each step of the demo recording in one plain line", () => {
    const steps = captionSteps(recording("20261102_demo_feature_agentic").events);
    const text = steps.map(captionText);
    expect(text[0]).toBe("Manager starts cleaning shop_app in safe mode");
    expect(text).toContain("Investigator #3 checks who calls _print_low_stock()");
    expect(text).toContain("Investigator #1 checks who uses bookshelf/inventory_old.py");
    expect(text).toContain("Tester measures the baseline (3 runs): 12 pass, 0 fail, 0 flaky");
    expect(text).toContain("Validator probes P4: behavior changed in 4 of 20 cases");
    expect(text).toContain("Engineer replaces _round_money() with the original it duplicates");
    expect(text).toContain("Investigator #7 leaves cmd_add() as a suggestion for a person");
    expect(text[text.length - 1]).toBe("Manager ends the run: everything runs, 5 edits applied");
    // LLM waits and raw tool results have no caption; decisions are marked for the space bar
    expect(steps.length).toBe(158);
    expect(steps.filter((s) => s.decision).map((s) => s.text).slice(-5)).toEqual(["keeps P3", "rolls back P4", "decides to continue", "keeps P5", "keeps P6"]);
    expect(captionFor(ev("llm_start", "explorer", { n: 1 }), fold([]))).toBeNull();
  });

  it("names a step back and a revert", () => {
    const text = captionSteps(recording("20261101_manager_conflict_step_back").events).map(captionText);
    expect(text).toContain("Manager steps back to execution");
    expect(text).toContain("Engineer reverts P2");
    expect(text).toContain("Tester runs the whole suite: 1 pass (baseline 2), 1 new failure");
  });

  it("reads a candidate the way a sentence needs it", () => {
    const state = fold(recording("20261102_demo_feature_agentic").events);
    const labels = state.itemOrder.map((id) => itemLabel(state.items[id]));
    expect(labels).toEqual(expect.arrayContaining(["scratch_restock.py", "_round_money()", "line 37 of bookshelf/inventory.py"]));
  });
});

describe("presentation pacing", () => {
  it("jumps from step to step through the decisions only, then stops at the end", () => {
    const steps = captionSteps(recording("20261102_demo_feature_agentic").events);
    const stops: number[] = [];
    for (let at = 0, k = 0; k < 20; k++) {
      at = nextDecisionStep(steps, at);
      if (stops.includes(at)) break;
      stops.push(at);
    }
    expect(stops.slice(0, -1).every((k) => steps[k].decision)).toBe(true);
    expect(stops[stops.length - 1]).toBe(steps.length - 1);
    expect(stops.length).toBe(steps.filter((s) => s.decision).length + 1);
  });

  it("makes before / after slides: the summary, one per change, the summary again", () => {
    const { events, report } = recording("20261102_demo_feature_agentic");
    const slides = afterSlides(parseDiff(report.stats.final_diff), fold(events));
    expect(slides.map((s) => (s.kind === "change" ? `${s.n}/${s.of}:${s.file.path}` : s.kind))).toEqual([
      "summary",
      "1/5:bookshelf/inventory.py",
      "2/5:bookshelf/inventory_old.py",
      "3/5:bookshelf/reports.py",
      "4/5:bookshelf/utils.py",
      "5/5:scratch_restock.py",
      "summary",
    ]);
  });
});
