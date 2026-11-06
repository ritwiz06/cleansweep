// A unified diff (git diff) as files and hunks, and a hunk as side-by-side rows.

export interface Hunk {
  oldStart: number;
  oldCount: number;
  newStart: number;
  newCount: number;
  header: string;
  lines: string[];
}

export interface DiffFile {
  path: string;
  oldPath: string;
  status: "added" | "removed" | "edited" | "renamed";
  header: string[];
  lines: string[];
  added: number;
  removed: number;
  hunks: Hunk[];
}

const HEADER = /^(index |--- |\+\+\+ |new file|deleted file|similarity|rename|old mode|new mode)/;
const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;

function newFile(path: string, header: string[]): DiffFile {
  return { path, oldPath: path, status: "edited", header, lines: [], added: 0, removed: 0, hunks: [] };
}

function settle(f: DiffFile) {
  for (const h of f.header) {
    if (h.startsWith("deleted file") || h === "+++ /dev/null") f.status = "removed";
    else if (h.startsWith("new file") || h === "--- /dev/null") f.status = "added";
    else if (h.startsWith("rename from ")) {
      f.oldPath = h.slice("rename from ".length);
      f.status = "renamed";
    }
  }
}

export function parseDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  for (const line of text.split("\n")) {
    if (line.startsWith("diff --git ")) {
      current = newFile(line.split(" b/").pop() || line, [line]);
      files.push(current);
      continue;
    }
    if (!current) {
      if (!line.trim()) continue;
      current = newFile("(diff)", []);
      files.push(current);
    }
    if (!current.lines.length && HEADER.test(line)) {
      current.header.push(line);
      continue;
    }
    current.lines.push(line);
    const m = HUNK.exec(line);
    if (m) {
      current.hunks.push({
        oldStart: Number(m[1]),
        oldCount: m[2] === undefined ? 1 : Number(m[2]),
        newStart: Number(m[3]),
        newCount: m[4] === undefined ? 1 : Number(m[4]),
        header: line,
        lines: [],
      });
      continue;
    }
    const hunk = current.hunks[current.hunks.length - 1];
    if (hunk && line && !line.startsWith("\\")) hunk.lines.push(line);
    if (line.startsWith("+")) current.added += 1;
    else if (line.startsWith("-")) current.removed += 1;
  }
  for (const f of files) settle(f);
  return files;
}

export interface Side {
  n: number;
  text: string;
  kind: "ctx" | "del" | "add";
}

export interface SideRow {
  left: Side | null;
  right: Side | null;
}

// A hunk's lines side by side: context on both sides, each run of removed lines paired with the
// added lines that follow it.
export function sideBySide(h: Hunk): SideRow[] {
  const rows: SideRow[] = [];
  let a = h.oldStart;
  let b = h.newStart;
  let i = 0;
  while (i < h.lines.length) {
    const line = h.lines[i];
    if (line[0] !== "-" && line[0] !== "+") {
      rows.push({ left: { n: a++, text: line.slice(1), kind: "ctx" }, right: { n: b++, text: line.slice(1), kind: "ctx" } });
      i += 1;
      continue;
    }
    const dels: string[] = [];
    const adds: string[] = [];
    while (i < h.lines.length && h.lines[i][0] === "-") dels.push(h.lines[i++].slice(1));
    while (i < h.lines.length && h.lines[i][0] === "+") adds.push(h.lines[i++].slice(1));
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
      rows.push({
        left: k < dels.length ? { n: a++, text: dels[k], kind: "del" } : null,
        right: k < adds.length ? { n: b++, text: adds[k], kind: "add" } : null,
      });
    }
  }
  return rows;
}
