import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fileStats, fileTrees, isTestFile, metrics } from "./beforeAfter";
import { parseDiff } from "./diff";
import { fold, type StudioEvent } from "./fold";
import { filesFromEvents } from "./tree";

const DIFF = [
  "diff --git a/pkg/a.py b/pkg/a.py",
  "@@ -1,3 +1,1 @@",
  "-x = 1",
  "-y = 2",
  " z = 3",
  "diff --git a/pkg/old/x.py b/pkg/old/x.py",
  "deleted file mode 100644",
  "@@ -1,4 +0,0 @@",
  "-a",
  "-b",
  "-c",
  "-d",
  "diff --git a/new.py b/new.py",
  "new file mode 100644",
  "@@ -0,0 +1,2 @@",
  "+n = 1",
  "+m = 2",
].join("\n");

const LIST = [
  { path: "pkg/a.py", lines: 10 },
  { path: "pkg/old/x.py", lines: 4 },
  { path: "README.md", lines: 3 },
  { path: "tests/test_a.py", lines: 5 },
];

function recording(name: string) {
  const base = new URL(`../../../../../demo/replay/${name}/`, import.meta.url);
  const events: StudioEvent[] = readFileSync(new URL("events.jsonl", base), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const report = JSON.parse(readFileSync(new URL("report.json", base), "utf8"));
  return { events, report, diff: report.stats.final_diff as string };
}

describe("before and after", () => {
  it("works out each file's lines after, and the folders that disappeared", () => {
    const stats = fileStats(LIST, parseDiff(DIFF));
    expect(stats["pkg/a.py"]).toMatchObject({ status: "edited", before: 10, after: 8, removed: 2 });
    expect(stats["pkg/old/x.py"]).toMatchObject({ status: "removed", before: 4, after: null });
    expect(stats["new.py"]).toMatchObject({ status: "added", before: null, after: 2 });
    expect(stats["README.md"].status).toBe("unchanged");
    const { before, after, gone } = fileTrees(stats);
    expect(gone).toEqual(["pkg/old"]);
    expect(before.children.map((c) => `${c.name}:${c.status}`)).toEqual(["pkg:edited", "tests:unchanged", "README.md:unchanged"]);
    expect(after.children.map((c) => c.name)).toEqual(["pkg", "tests", "new.py", "README.md"]);
    expect(after.children[0].children.map((c) => c.name)).toEqual(["a.py"]);
  });

  it("counts files and non-test Python lines before and after from a saved file list", () => {
    const m = metrics(fold([]), fileStats(LIST, parseDiff(DIFF)), true);
    expect(m.files).toEqual({ before: 4, after: 4 });
    expect(m.pyFiles).toEqual({ before: 3, after: 3 });
    expect(m.loc).toEqual({ before: 14, after: 10, source: "file list" });
    expect([m.linesRemoved, m.linesAdded]).toEqual([6, 2]);
    expect(isTestFile("tests/test_a.py") && isTestFile("pkg/conftest.py") && !isTestFile("pkg/testing.py")).toBe(true);
  });

  it("reads the demo recording's numbers from its events, diff and report", () => {
    const { events, report, diff } = recording("20261102_demo_feature_agentic");
    const state = fold(events);
    const files = filesFromEvents(events).map((path) => ({ path, lines: null }));
    const stats = fileStats(files, parseDiff(diff));
    const m = metrics(state, stats, false, report.stats);
    expect(m.files).toEqual({ before: null, after: null });
    expect(m.pyFiles).toEqual({ before: 16, after: 14 });
    expect(m.loc).toEqual({ before: 229, after: 182, source: "hidden checks" });
    expect(m.linesRemoved - m.linesAdded).toBe(report.stats.lines_removed);
    expect(m.slop.find((s) => s.category === "dead_code")).toEqual({ category: "dead_code", before: 9, after: 7 });
    expect(m.slop.find((s) => s.category === "duplicate")).toEqual({ category: "duplicate", before: 2, after: 1 });
    expect(m.tests).toMatchObject({ passed: { before: 12, after: 12 }, failing: 0, newFailures: [], flaky: 0 });
    expect(m.probes).toEqual({ cases: 70, coverage: 0.75, measured: 1, packages: 5 });
    // P6 removed a public function: the card says so instead of "unchanged"
    expect(m.publicApi).toEqual({ checked: 5, removed: ["bookshelf/utils.py::isbn_checksum_ok"] });
    expect(m.verdict).toBe("everything runs");
  });
});
