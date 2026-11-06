import { describe, expect, it } from "vitest";
import { parseDiff, sideBySide } from "./diff";

const DIFF = [
  "diff --git a/pkg/a.py b/pkg/a.py",
  "index 1..2 100644",
  "--- a/pkg/a.py",
  "+++ b/pkg/a.py",
  "@@ -1,4 +1,3 @@",
  " import x",
  "-import os",
  "-def old():",
  "+def new():",
  "     pass",
  "@@ -10 +9,2 @@ def f():",
  "-    return 1",
  "+    return 2",
  "+    # done",
  "\\ No newline at end of file",
  "diff --git a/gone.py b/gone.py",
  "deleted file mode 100644",
  "--- a/gone.py",
  "+++ /dev/null",
  "@@ -1,2 +0,0 @@",
  "-a = 1",
  "-b = 2",
  "diff --git a/new.py b/new.py",
  "new file mode 100644",
  "--- /dev/null",
  "+++ b/new.py",
  "@@ -0,0 +1 @@",
  "+c = 3",
  "diff --git a/old_name.py b/new_name.py",
  "similarity index 100%",
  "rename from old_name.py",
  "rename to new_name.py",
  "",
].join("\n");

describe("parseDiff", () => {
  it("reads each file's status, hunks and counts", () => {
    const files = parseDiff(DIFF);
    expect(files.map((f) => [f.path, f.status, f.added, f.removed, f.hunks.length])).toEqual([
      ["pkg/a.py", "edited", 3, 3, 2],
      ["gone.py", "removed", 0, 2, 1],
      ["new.py", "added", 1, 0, 1],
      ["new_name.py", "renamed", 0, 0, 0],
    ]);
    expect(files[3].oldPath).toBe("old_name.py");
    expect(files[0].hunks[1]).toMatchObject({ oldStart: 10, oldCount: 1, newStart: 9, newCount: 2 });
  });

  it("pairs removed lines with the added lines after them, side by side", () => {
    const rows = sideBySide(parseDiff(DIFF)[0].hunks[0]);
    expect(rows.map((r) => [r.left && `${r.left.n}${r.left.kind[0]}`, r.right && `${r.right.n}${r.right.kind[0]}`])).toEqual([
      ["1c", "1c"],
      ["2d", "2a"],
      ["3d", null],
      ["4c", "3c"],
    ]);
    expect(rows[1].right?.text).toBe("def new():");
  });
});
