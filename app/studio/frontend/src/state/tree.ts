// The project's file tree with every candidate on it: folders, files, classes, functions and
// line ranges, each in the state the events put it in, with the agent that acted on it last.
import type { RunState, StudioEvent } from "./fold";

export interface FileEntry {
  path: string;
  lines: number | null;
}

export type NodeKind = "folder" | "file" | "class" | "function" | "lines" | "import" | "dependency";

export interface TreeNode {
  key: string;
  name: string;
  kind: NodeKind;
  path: string;
  children: TreeNode[];
  own: string[]; // the candidates on this node itself
  items: string[]; // the candidates on this node and below
  state: string;
  counts: Record<string, number>;
  actor: string | null;
  lastT: number;
  focus: boolean;
  lines: number | null;
}

// Which state a node shows when its candidates differ: what is happening now, then outcomes,
// then verdicts.
export const PRIORITY = [
  "investigating",
  "in_package",
  "rolled_back",
  "kept",
  "repaired",
  "safe",
  "candidate",
  "suggest",
  "dropped",
  "skipped",
];

const KIND_ORDER: Record<NodeKind, number> = {
  folder: 0,
  file: 1,
  class: 2,
  function: 3,
  import: 4,
  dependency: 5,
  lines: 6,
};

export function splitUnit(unit: string): { path: string; rest: string | null } {
  const i = unit.indexOf("::");
  return i < 0 ? { path: unit, rest: null } : { path: unit.slice(0, i), rest: unit.slice(i + 2) };
}

export function pickState(states: string[]): string {
  for (const s of PRIORITY) if (states.includes(s)) return s;
  return "untouched";
}

// The files a run's events name, for a run that saved no file list: the Explorer's entry
// points and config files, the candidates, and the files agents read.
export function filesFromEvents(events: StudioEvent[]): string[] {
  const found = new Set<string>();
  const add = (value: unknown) => {
    if (typeof value === "string" && value && !value.startsWith("/")) found.add(splitUnit(value).path);
  };
  for (const e of events) {
    const p = e.payload || {};
    if (e.kind === "tool_result" && p.tool === "project_facts") {
      for (const key of ["entry_points", "config_files", "ci_files"]) (p.result?.[key] || []).forEach(add);
    } else if (e.kind === "message" && p.type === "candidates") {
      for (const c of p.body?.items || []) add(c.unit);
    } else if (e.kind === "tool_call" && /^read_(file|code)$/.test(p.tool)) {
      add(p.args?.path);
    }
  }
  return [...found].sort();
}

function node(key: string, name: string, kind: NodeKind, path: string, lines: number | null = null): TreeNode {
  return { key, name, kind, path, children: [], own: [], items: [], state: "untouched", counts: {}, actor: null, lastT: -1, focus: false, lines };
}

function child(parent: TreeNode, key: string, make: () => TreeNode): TreeNode {
  let found = parent.children.find((c) => c.key === key);
  if (!found) {
    found = make();
    parent.children.push(found);
  }
  return found;
}

function fileNode(root: TreeNode, path: string, lines: number | null = null): TreeNode {
  const parts = path.split("/");
  let at = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const dir = parts.slice(0, i + 1).join("/");
    at = child(at, `dir:${dir}`, () => node(`dir:${dir}`, parts[i], "folder", dir));
  }
  const file = child(at, `file:${path}`, () => node(`file:${path}`, parts[parts.length - 1], "file", path, lines));
  if (lines !== null) file.lines = lines;
  return file;
}

function lineLabel(rest: string): string | null {
  const m = /^L(\d+)-(\d+)$/.exec(rest);
  if (!m) return null;
  return m[1] === m[2] ? `line ${m[1]}` : `lines ${m[1]}–${m[2]}`;
}

// The node a candidate sits on, made as needed under its file.
function unitNode(file: TreeNode, rest: string, category: string): TreeNode {
  const key = (k: string) => `unit:${file.path}::${k}`;
  const lines = lineLabel(rest);
  if (lines) return child(file, key(rest), () => node(key(rest), lines, "lines", file.path));
  if (category === "unused_import") return child(file, key(rest), () => node(key(rest), `import ${rest}`, "import", file.path));
  if (category === "unused_dependency") return child(file, key(rest), () => node(key(rest), rest, "dependency", file.path));
  const parts = rest.split(".");
  let at = file;
  parts.forEach((part, i) => {
    const name = parts.slice(0, i + 1).join(".");
    const last = i === parts.length - 1;
    const kind: NodeKind = !last || /^[A-Z]/.test(part) ? "class" : "function";
    at = child(at, key(name), () => node(key(name), kind === "function" ? `${part}()` : part, kind, file.path));
  });
  return at;
}

function lineOf(n: TreeNode): number {
  const m = /::L(\d+)/.exec(n.key);
  return m ? Number(m[1]) : 0;
}

function finish(n: TreeNode, state: RunState, focus: Set<string>): void {
  n.children.sort(
    (a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || lineOf(a) - lineOf(b) || a.name.localeCompare(b.name),
  );
  for (const c of n.children) finish(c, state, focus);
  n.items = [...n.own, ...n.children.flatMap((c) => c.items)];
  const stages = n.items.map((id) => state.items[id].stage);
  n.counts = {};
  for (const s of stages) n.counts[s] = (n.counts[s] || 0) + 1;
  n.state = pickState(stages);
  for (const id of n.items) {
    const item = state.items[id];
    if (item.lastT > n.lastT) {
      n.lastT = item.lastT;
      n.actor = item.actor;
    }
  }
  n.focus = n.items.some((id) => focus.has(id));
}

export function buildTree(files: FileEntry[], state: RunState, name = "project"): TreeNode {
  const root = node("root", name, "folder", "");
  for (const f of files) fileNode(root, f.path, f.lines);
  for (const id of state.itemOrder) {
    const item = state.items[id];
    const { path, rest } = splitUnit(item.unit || id);
    const file = fileNode(root, path);
    (rest ? unitNode(file, rest, item.category) : file).own.push(id);
  }
  finish(root, state, new Set(state.focus));
  return root;
}

export function countNodes(n: TreeNode): number {
  return 1 + n.children.reduce((a, c) => a + countNodes(c), 0);
}

// Open everything in a small tree; in a big one, only the folders that hold candidates.
export function defaultExpanded(root: TreeNode, small = 150): Set<string> {
  const open = new Set<string>();
  const all = countNodes(root) <= small;
  const walk = (n: TreeNode) => {
    if (n.children.length && (all || (n.kind === "folder" && n.items.length))) open.add(n.key);
    n.children.forEach(walk);
  };
  walk(root);
  return open;
}

// The keys of the nodes on the way to every focused node (to open them when following).
export function focusPath(root: TreeNode): string[] {
  const out: string[] = [];
  const walk = (n: TreeNode) => {
    if (!n.focus) return;
    if (n.children.some((c) => c.focus)) out.push(n.key);
    n.children.forEach(walk);
  };
  walk(root);
  return out;
}

export interface Row {
  node: TreeNode;
  depth: number;
}

// The rows a tree shows with these nodes open (the root itself is not a row).
export function visibleRows(root: TreeNode, open: Set<string>): Row[] {
  const rows: Row[] = [];
  const walk = (n: TreeNode, depth: number) => {
    for (const c of n.children) {
      rows.push({ node: c, depth });
      if (open.has(c.key)) walk(c, depth + 1);
    }
  };
  walk(root, 0);
  return rows;
}

// The keys from the root down to a node (without the node), or [] if it is not in the tree.
export function pathTo(root: TreeNode, key: string): string[] {
  for (const c of root.children) {
    if (c.key === key) return [root.key];
    const below = pathTo(c, key);
    if (below.length) return [root.key, ...below];
  }
  return [];
}

export function findNode(root: TreeNode, key: string): TreeNode | null {
  if (root.key === key) return root;
  for (const c of root.children) {
    const hit = findNode(c, key);
    if (hit) return hit;
  }
  return null;
}
