import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { annotateFile, categoryLabel, decisionSteps, packageChecks } from "./annotate";
import { parseDiff } from "./diff";
import { fold, roleOf, type StudioEvent } from "./fold";

function recording(name: string) {
  const base = new URL(`../../../../../demo/replay/${name}/`, import.meta.url);
  const events: StudioEvent[] = readFileSync(new URL("events.jsonl", base), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const report = JSON.parse(readFileSync(new URL("report.json", base), "utf8"));
  return { state: fold(events), files: parseDiff(report.stats.final_diff) };
}

describe("diff annotation", () => {
  it("ties every hunk of the demo's final diff to the candidate it removes", () => {
    const { state, files } = recording("20261102_demo_feature_agentic");
    const units = files.map((f) => [f.path, annotateFile(f, state).map((n) => `${n.match}:${n.items.map((id) => state.items[id].unit).join("+")}`)]);
    expect(units).toEqual([
      ["bookshelf/inventory.py", ["exact:bookshelf/inventory.py::_print_low_stock"]],
      ["bookshelf/inventory_old.py", ["exact:bookshelf/inventory_old.py"]],
      ["bookshelf/reports.py", ["exact:bookshelf/reports.py::_clean_isbn"]],
      ["bookshelf/utils.py", ["exact:bookshelf/utils.py::isbn_checksum_ok"]],
      ["scratch_restock.py", ["exact:scratch_restock.py"]],
    ]);
  });

  it("ties the toy run's imports, duplicates and wrapper to their hunks", () => {
    const { state, files } = recording("20261101_toy_clean_offline");
    for (const f of files) {
      for (const note of annotateFile(f, state)) expect(note.match, f.path).not.toBe("none");
    }
    const cart = files.find((f) => f.path === "shopcart/cart.py")!;
    const units = annotateFile(cart, state).flatMap((n) => n.items.map((id) => state.items[id].category));
    expect(units).toContain("unused_import");
  });

  it("lists the decisions and the checks behind an applied candidate", () => {
    const { state } = recording("20261102_demo_feature_agentic");
    const item = Object.values(state.items).find((i) => i.unit === "bookshelf/reports.py::_clean_isbn")!;
    const steps = decisionSteps(item, state);
    expect(steps.map((s) => roleOf(s.agent))).toEqual(["auditor", "investigator", "planner", "engineer", "tester", "validator", "manager"]);
    expect(steps[0].text).toBe("flagged it as duplicate (safe lane)");
    expect(steps[steps.length - 1].text).toBe("P5 kept");
    expect(packageChecks(state.packages[item.pkg!]).map((c) => `${c.ok}:${c.label}`)).toEqual([
      "true:tests pass",
      "true:24 probe cases: same before and after",
      "null:probe coverage of the changed lines 75%",
      "true:public names unchanged",
    ]);
    expect(categoryLabel("debug_leftover")).toBe("debug print");
  });
});
