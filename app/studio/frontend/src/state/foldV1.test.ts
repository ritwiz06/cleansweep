import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { foldV1 } from "./foldV1";
import { clockOf, countAt, nextDecision } from "./replay";

const RECORDING = new URL(
  "../../../../../demo/replay/20261030_demo_feature_advisory_v1/events.jsonl",
  import.meta.url,
);

function recording() {
  return readFileSync(RECORDING, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

describe("foldV1", () => {
  it("folds a shipped recording to its end state", () => {
    const s = foldV1(recording());
    expect(s.stages.done).toBe("done");
    expect(s.hidden.behavior_changed).toBe(false);
    expect(s.kept).toBeGreaterThan(0);
    expect(s.batches.filter((b) => b.probes && !b.probes.same)).toHaveLength(2);
    expect(s.report).toContain("report.json");
  });

  it("shows a running stage on a partial log", () => {
    const events = recording();
    const s = foldV1(events.slice(0, 2));
    expect(s.current).toBe("open");
    expect(s.stages.open).toBe("running");
  });
});

describe("replay clock", () => {
  const events = [
    { t: 0, kind: "run_start" },
    { t: 1, kind: "message" },
    { t: 1, kind: "decision", payload: { rule: "package_done" } },
    { t: 5, kind: "phase_change", payload: { back: false } },
    { t: 9, kind: "phase_change", payload: { back: true } },
  ];

  it("counts the events up to a time", () => {
    expect(countAt(events, -1)).toBe(0);
    expect(countAt(events, 1)).toBe(3);
    expect(countAt(events, 4.9)).toBe(3);
    expect(countAt(events, 100)).toBe(5);
    expect(clockOf(events, 4)).toBe(5);
    expect(clockOf(events, 0)).toBe(0);
  });

  it("jumps to the next decision or step back", () => {
    expect(nextDecision(events, 0)).toBe(3);
    expect(nextDecision(events, 3)).toBe(5);
    expect(nextDecision(events, 5)).toBe(5);
  });
});
