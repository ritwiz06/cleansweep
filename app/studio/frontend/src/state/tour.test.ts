import { describe, expect, it } from "vitest";
import { MARGIN, placeCard, scrollDelta, spotlight } from "./tour";

const VIEW = { width: 1280, height: 720 };
const CARD = { width: 380, height: 180 };

describe("placeCard", () => {
  it("puts the card below a target near the top, aligned with its left edge", () => {
    const at = placeCard({ top: 60, left: 220, width: 900, height: 50 }, CARD, VIEW);
    expect(at).toEqual({ top: 122, left: 220, side: "below" });
  });

  it("puts the card above a target near the bottom", () => {
    const at = placeCard({ top: 560, left: 300, width: 400, height: 100 }, CARD, VIEW);
    expect(at.side).toBe("above");
    expect(at.top).toBe(560 - 12 - 180);
  });

  it("puts the card in the top right corner of a target that fills the screen", () => {
    const at = placeCard({ top: 40, left: 220, width: 1000, height: 660 }, CARD, VIEW);
    expect(at).toEqual({ top: 56, left: 220 + 1000 - CARD.width - MARGIN, side: "inside" });
  });

  it("keeps the card inside the viewport", () => {
    const at = placeCard({ top: 20, left: 1100, width: 900, height: 700 }, CARD, VIEW);
    expect(at.left).toBe(VIEW.width - MARGIN - CARD.width);
    expect(at.top + CARD.height).toBeLessThanOrEqual(VIEW.height - MARGIN);
  });
});

describe("scrollDelta", () => {
  it("brings a target and the card under it on screen together", () => {
    const target = { top: 380, left: 220, width: 1000, height: 470 };
    const delta = scrollDelta(target, 190, 720);
    const top = target.top - delta;
    expect(top).toBeGreaterThanOrEqual(MARGIN);
    expect(placeCard({ ...target, top }, CARD, VIEW).side).toBe("below");
  });

  it("puts a target too tall for that at the top of the screen", () => {
    expect(scrollDelta({ top: 300, left: 0, width: 100, height: 900 }, 190, 720)).toBe(300 - MARGIN);
  });
});

describe("spotlight", () => {
  it("pads the target and clips it to the viewport", () => {
    expect(spotlight({ top: 100, left: 200, width: 300, height: 40 }, VIEW)).toEqual({ top: 94, left: 194, width: 312, height: 52 });
    const clipped = spotlight({ top: 600, left: 1000, width: 400, height: 400 }, VIEW);
    expect(clipped.top + clipped.height).toBe(716);
    expect(clipped.left + clipped.width).toBe(1276);
  });
});
