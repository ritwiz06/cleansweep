import { describe, expect, it } from "vitest";
import { seconds } from "./common";

describe("seconds", () => {
  it("rounds before it splits off the minutes", () => {
    expect(seconds(119.6)).toBe("2 min 0 s");
    expect(seconds(74.2)).toBe("1 min 14 s");
    expect(seconds(59.4)).toBe("59 s");
    expect(seconds(9.24)).toBe("9.2 s");
    expect(seconds(null)).toBe("-");
  });
});
