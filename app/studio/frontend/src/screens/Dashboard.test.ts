import { describe, expect, it } from "vitest";
import { restoreCommand } from "./Dashboard";

describe("restoreCommand", () => {
  it("copies a quarantined file back to its place", () => {
    const evidence = ["unused file", "quarantined at .cleansweep/quarantine/x/1/debug_cart.py"];
    expect(restoreCommand(evidence, "shopcart/debug_cart.py")).toBe("cp '.cleansweep/quarantine/x/1/debug_cart.py' 'shopcart/debug_cart.py'");
  });

  it("is null when nothing was quarantined", () => {
    expect(restoreCommand(["llm judge: remove (confidence 0.9)"], "a.py")).toBeNull();
  });
});
