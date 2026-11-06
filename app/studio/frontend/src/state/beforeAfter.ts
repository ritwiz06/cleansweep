// Before and after a cleanup: both file trees and the numbers, from the project's file list,
// the final diff and the folded events.
import { parseDiff, type DiffFile } from "./diff";
import { fold, type RunState, type StudioEvent } from "./fold";
import { filesFromEvents, type FileEntry } from "./tree";

export type FileStatus = "removed" | "edited" | "added" | "unchanged";

export interface FileStat {
  path: string;
  status: FileStatus;
  added: number;
  removed: number;
  before: number | null;
  after: number | null;
}

export interface FileTree {
  key: string;
  name: string;
  path: string;
  kind: "folder" | "file";
  children: FileTree[];
  status: FileStatus | "gone";
  added: number;
  removed: number;
  lines: number | null;
}

// The same test-file rule as cleansweep.analysis.graph.is_test_file.
export function isTestFile(path: string): boolean {
  const parts = path.split("/");
  const name = parts.pop() || "";
  return name.startsWith("test_") || name.endsWith("_test.py") || name === "conftest.py" || parts.includes("tests") || parts.includes("test");
}

export function fileStats(files: FileEntry[], diff: DiffFile[]): Record<string, FileStat> {
  const out: Record<string, FileStat> = {};
  for (const f of files) out[f.path] = { path: f.path, status: "unchanged", added: 0, removed: 0, before: f.lines, after: f.lines };
  for (const d of diff) {
    if (d.status === "renamed" && out[d.oldPath]) {
      out[d.oldPath] = { ...out[d.oldPath], status: "removed", after: null };
    }
    const known = out[d.status === "renamed" ? d.oldPath : d.path];
    const before = d.status === "added" ? null : known ? known.before : d.status === "removed" ? d.removed : null;
    const status: FileStatus = d.status === "renamed" ? "added" : d.status;
    out[d.path] = {
      path: d.path,
      status,
      added: d.added,
      removed: d.removed,
      before,
      after: status === "removed" ? null : before === null ? (status === "added" ? d.added : null) : before - d.removed + d.added,
    };
  }
  return out;
}

function folder(key: string, name: string, path: string): FileTree {
  return { key, name, path, kind: "folder", children: [], status: "unchanged", added: 0, removed: 0, lines: null };
}

function place(root: FileTree, s: FileStat, lines: number | null) {
  const parts = s.path.split("/");
  let at = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const path = parts.slice(0, i + 1).join("/");
    let next = at.children.find((c) => c.key === `dir:${path}`);
    if (!next) {
      next = folder(`dir:${path}`, parts[i], path);
      at.children.push(next);
    }
    at = next;
  }
  at.children.push({ key: `file:${s.path}`, name: parts[parts.length - 1], path: s.path, kind: "file", children: [], status: s.status, added: s.added, removed: s.removed, lines });
}

// A folder sums its files' changes; in the before tree, a folder whose every file was removed is gone.
function settle(n: FileTree): void {
  n.children.sort((a, b) => Number(a.kind === "file") - Number(b.kind === "file") || a.name.localeCompare(b.name));
  for (const c of n.children) settle(c);
  if (n.kind === "file") return;
  n.added = n.children.reduce((a, c) => a + c.added, 0);
  n.removed = n.children.reduce((a, c) => a + c.removed, 0);
  const states = n.children.map((c) => c.status);
  if (states.length && states.every((s) => s === "removed" || s === "gone")) n.status = "gone";
  else if (states.some((s) => s !== "unchanged")) n.status = "edited";
}

export function fileTrees(stats: Record<string, FileStat>, name = "project"): { before: FileTree; after: FileTree; gone: string[] } {
  const before = folder("root", name, "");
  const after = folder("root", name, "");
  for (const s of Object.values(stats)) {
    if (s.status !== "added") place(before, s, s.before);
    if (s.status !== "removed") place(after, s, s.after);
  }
  settle(before);
  settle(after);
  const gone: string[] = [];
  const walk = (n: FileTree) => {
    if (n.kind === "folder" && n.status === "gone") gone.push(n.path);
    else n.children.forEach(walk);
  };
  before.children.forEach(walk);
  return { before, after, gone };
}

export interface Pair {
  before: number | null;
  after: number | null;
}

export interface Metrics {
  files: Pair;
  pyFiles: Pair;
  loc: Pair & { source: "file list" | "hidden checks" | null };
  linesRemoved: number;
  linesAdded: number;
  slop: { category: string; before: number; after: number }[];
  // the final suite runs once: it reports what passes and what newly fails, not flaky tests
  tests: { passed: Pair; failing: number; newFailures: string[]; flaky: number; removed: string[] } | null;
  probes: { cases: number; coverage: number | null; measured: number; packages: number };
  publicApi: { checked: number; removed: string[] };
  verdict: string | null;
  finished: boolean;
}

const APPLIED = ["kept", "repaired"];

function sum(xs: (number | null)[]): number | null {
  return xs.some((x) => x === null) ? null : xs.reduce<number>((a, x) => a + (x as number), 0);
}

export function metrics(state: RunState, stats: Record<string, FileStat>, complete: boolean, report: any = null): Metrics {
  const all = Object.values(stats);
  const removed = all.filter((s) => s.status === "removed");
  const addedFiles = all.filter((s) => s.status === "added");
  const py = (s: FileStat) => s.path.endsWith(".py");
  const pyBefore = complete ? all.filter((s) => py(s) && s.status !== "added").length : (state.facts?.python_files ?? null);
  const pyDelta = addedFiles.filter(py).length - removed.filter(py).length;
  const code = all.filter((s) => py(s) && !isTestFile(s.path));
  let loc: Metrics["loc"] = { before: null, after: null, source: null };
  if (complete) {
    loc = { before: sum(code.filter((s) => s.status !== "added").map((s) => s.before)), after: sum(code.filter((s) => s.status !== "removed").map((s) => s.after)), source: "file list" };
  } else if (typeof report?.hidden?.loc_before === "number") {
    loc = { before: report.hidden.loc_before, after: report.hidden.loc_after, source: "hidden checks" };
  }
  const byCategory: Record<string, { before: number; after: number }> = {};
  for (const id of state.itemOrder) {
    const item = state.items[id];
    const row = (byCategory[item.category] ||= { before: 0, after: 0 });
    row.before += 1;
    if (!APPLIED.includes(item.stage)) row.after += 1;
  }
  const base = state.baseline;
  const final = state.summary?.final || state.finalCheck;
  const kept = state.packageOrder.map((id) => state.packages[id]).filter((p) => APPLIED.includes(p.status));
  const coverage = kept.map((p) => p.coverage).filter((c): c is number => typeof c === "number");
  return {
    files: complete ? { before: all.length - addedFiles.length, after: all.length - removed.length } : { before: null, after: null },
    pyFiles: { before: pyBefore, after: pyBefore === null ? null : pyBefore + pyDelta },
    loc,
    linesRemoved: all.reduce((a, s) => a + s.removed, 0),
    linesAdded: all.reduce((a, s) => a + s.added, 0),
    slop: Object.entries(byCategory)
      .map(([category, n]) => ({ category, ...n }))
      .sort((a, b) => b.before - a.before || a.category.localeCompare(b.category)),
    tests: base
      ? {
          passed: { before: base.passed ?? null, after: final?.passed ?? null },
          failing: (base.failed ?? 0) + (base.errors ?? 0),
          newFailures: final?.new_failures || [],
          flaky: (base.flaky || []).length,
          removed: final?.tests_removed || [],
        }
      : null,
    probes: {
      cases: state.probes,
      coverage: coverage.length ? coverage.reduce((a, c) => a + c, 0) / coverage.length : null,
      measured: coverage.length,
      packages: kept.length,
    },
    publicApi: {
      checked: kept.filter((p) => p.validation).length,
      removed: [...new Set(kept.flatMap((p) => p.validation?.checks?.public_api_removed || []))],
    },
    verdict: state.verdict,
    finished: state.finished,
  };
}

export interface AfterModel {
  state: RunState;
  parsed: DiffFile[];
  list: FileEntry[];
  trees: { before: FileTree; after: FileTree; gone: string[] };
  m: Metrics;
  name: string;
}

// Before / after from a run's events, its final diff, its saved file list (if any) and its report.
export function afterModel(
  events: StudioEvent[],
  diff: string,
  files: { files: FileEntry[]; complete: boolean } | null,
  run: { target?: string | null; report?: { stats?: any } | null },
): AfterModel {
  const state = fold(events);
  const parsed = parseDiff(diff);
  const list = files?.complete ? files.files : filesFromEvents(events).map((path) => ({ path, lines: null }));
  const stats = fileStats(list, parsed);
  const name = (state.repo || run.target || "project").replace(/^local:/, "");
  return { state, parsed, list, trees: fileTrees(stats, name), m: metrics(state, stats, Boolean(files?.complete), run.report?.stats), name };
}
