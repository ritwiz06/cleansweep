import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fold, type StudioEvent } from "./fold";
import { buildTree, defaultExpanded, filesFromEvents, findNode, focusPath, pickState, splitUnit, visibleRows } from "./tree";

let n = 0;
function ev(kind: string, agent: string | null, payload: object, extra: Partial<StudioEvent> = {}): StudioEvent {
  n += 1;
  return { id: `e${n}`, t: n, kind, agent, phase: null, recipients: [], artifacts: [], payload, ...extra };
}
const msg = (agent: string, type: string, body: object, recipients: string[]) =>
  ev("message", agent, { msg_id: `m${n}`, type, body }, { recipients });

function scenario(): StudioEvent[] {
  n = 0;
  return [
    ev("tool_result", "explorer", { tool: "project_facts", result: { entry_points: ["pkg/main.py", "tests/test_x.py::test_a"], config_files: ["pytest.ini"] } }),
    msg("auditor", "candidates", {
      items: [
        { item_id: "a", unit: "pkg/x.py::Shape.area", category: "dead_code", lane: "safe" },
        { item_id: "b", unit: "pkg/old.py", category: "leftover_file", lane: "safe" },
        { item_id: "c", unit: "pkg/x.py::L7-9", category: "commented_code", lane: "safe" },
        { item_id: "d", unit: "pkg/x.py::os", category: "unused_import", lane: "safe" },
      ],
    }, ["manager", "investigator"]),
    msg("manager", "task", { items: ["a"] }, ["investigator#1"]),
    ev("tool_call", "investigator#1", { tool: "read_code", args: { path: "pkg/helpers.py" } }),
    msg("investigator#1", "verdict", { item_id: "a", decision: "safe", reason: "unused", evidence: [] }, ["manager"]),
    msg("manager", "task", { items: ["b"] }, ["investigator#2"]),
    ev("tool_call", "investigator#2", { tool: "find_references", args: { name: "old" } }),
  ];
}

describe("splitUnit and pickState", () => {
  it("splits a unit at :: and picks what is happening now first", () => {
    expect(splitUnit("a/b.py::C.f")).toEqual({ path: "a/b.py", rest: "C.f" });
    expect(splitUnit("a/b.py")).toEqual({ path: "a/b.py", rest: null });
    expect(pickState(["kept", "suggest", "investigating"])).toBe("investigating");
    expect(pickState(["suggest", "kept"])).toBe("kept");
    expect(pickState([])).toBe("untouched");
  });
});

describe("the file tree", () => {
  it("names the files the events mention when the run saved no list", () => {
    expect(filesFromEvents(scenario())).toEqual(["pkg/helpers.py", "pkg/main.py", "pkg/old.py", "pkg/x.py", "pytest.ini", "tests/test_x.py"]);
  });

  it("puts each candidate on its file, class, function, import or lines, in its state", () => {
    const events = scenario();
    const state = fold(events);
    const tree = buildTree([{ path: "pkg/x.py", lines: 20 }, { path: "README.md", lines: 3 }], state);
    const x = findNode(tree, "file:pkg/x.py")!;
    expect(x.lines).toBe(20);
    expect(x.children.map((c) => `${c.kind}:${c.name}`)).toEqual(["class:Shape", "import:import os", "lines:lines 7–9"]);
    const area = findNode(tree, "unit:pkg/x.py::Shape.area")!;
    expect(area).toMatchObject({ kind: "function", name: "area()", state: "safe", actor: "investigator#1" });
    expect(x.counts).toEqual({ safe: 1, candidate: 2 });
    expect(x.state).toBe("safe");
    // the leftover file is a candidate itself, and the one being investigated now
    const old = findNode(tree, "file:pkg/old.py")!;
    expect(old).toMatchObject({ own: ["b"], state: "investigating", actor: "investigator#2", focus: true });
    expect(findNode(tree, "dir:pkg")!.state).toBe("investigating");
    expect(findNode(tree, "file:README.md")!.state).toBe("untouched");
    expect(focusPath(tree)).toEqual(["root", "dir:pkg"]);
  });

  it("opens a small tree fully and lists rows in order: folders, files, then units", () => {
    const tree = buildTree([{ path: "pkg/x.py", lines: 20 }, { path: "z.py", lines: 1 }], fold(scenario()));
    const rows = visibleRows(tree, defaultExpanded(tree));
    expect(rows.map((r) => `${r.depth}:${r.node.name}`).slice(0, 4)).toEqual(["0:pkg", "1:old.py", "1:x.py", "2:Shape"]);
    expect(visibleRows(tree, new Set()).map((r) => r.node.name)).toEqual(["pkg", "z.py"]);
    expect(defaultExpanded(tree, 3).has("file:pkg/x.py")).toBe(false);
  });

  it("covers every candidate of the shipped demo recording", () => {
    const text = readFileSync(new URL("../../../../../demo/replay/20261102_demo_feature_agentic/events.jsonl", import.meta.url), "utf8");
    const events: StudioEvent[] = text.trim().split("\n").map((line) => JSON.parse(line));
    const state = fold(events);
    const files = filesFromEvents(events);
    // the events name 15 of the brief's 16 Python files (the package's __init__.py never comes up)
    expect([files.filter((f) => f.endsWith(".py")).length, state.facts.python_files]).toEqual([15, 16]);
    const tree = buildTree(files.map((path) => ({ path, lines: null })), state);
    expect(tree.items.length).toBe(state.itemOrder.length);
    expect(tree.counts).toMatchObject({ kept: 5, rolled_back: 1 });
    expect(findNode(tree, "file:bookshelf/inventory_old.py")!).toMatchObject({ state: "kept", actor: "manager" });
    // mid-investigation, each investigator instance is on its own candidate
    const mid = fold(events.slice(0, events.findIndex((e) => e.id === "e00070")));
    const midTree = buildTree([], mid);
    expect(findNode(midTree, "unit:bookshelf/inventory.py::_print_low_stock")).toMatchObject({ state: "investigating", actor: "investigator#3" });
    expect(findNode(midTree, "file:scratch_restock.py")).toMatchObject({ actor: "investigator#2" });
  });
});
