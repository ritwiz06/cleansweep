import { describe, expect, it } from "vitest";
import { GAP, MIN_PHASE, labelWidth, phaseWidths, positionOf } from "./timeline";

describe("phaseWidths", () => {
  it("gives every phase its minimum and shares the rest by duration", () => {
    const widths = phaseWidths([10, 1, 1], 1000, [MIN_PHASE, MIN_PHASE, MIN_PHASE]);
    expect(widths.every((w) => w >= MIN_PHASE)).toBe(true);
    expect(widths.reduce((a, b) => a + b, 0) + 2 * GAP).toBeCloseTo(1000);
    expect(widths[0]).toBeGreaterThan(widths[1]);
  });

  it("keeps the current phase's whole name", () => {
    const mins = [MIN_PHASE, labelWidth("INVESTIGATE")];
    const widths = phaseWidths([100, 0], 600, mins);
    expect(widths[1]).toBeGreaterThanOrEqual(labelWidth("INVESTIGATE"));
  });

  it("shrinks the minimums evenly when the bar is too narrow", () => {
    const widths = phaseWidths([1, 1, 1], 150, [72, 72, 72]);
    expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(150 - 2 * GAP);
  });
});

describe("positionOf", () => {
  it("places a moment inside its phase", () => {
    const spans = [
      { start: 0, dur: 10 },
      { start: 10, dur: 10 },
    ];
    expect(positionOf(5, spans, [100, 200])).toBe(50);
    expect(positionOf(15, spans, [100, 200])).toBe(100 + GAP + 100);
  });
});
