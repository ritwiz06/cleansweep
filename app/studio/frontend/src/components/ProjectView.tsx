import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { api, useApi, type RunDetail } from "../api";
import type { Item, RunState, StudioEvent } from "../state/fold";
import { buildTree, defaultExpanded, filesFromEvents, findNode, focusPath, pathTo, visibleRows, type FileEntry, type TreeNode } from "../state/tree";
import { AgentIcon, AgentTag, agentName } from "./AgentIcon";
import { RunContext } from "./Artifact";
import { Pointer } from "./AfterParts";
import { DiffView, filterDiff } from "./Code";
import { Card, Empty, Loading } from "./common";
import { ItemDetail } from "./ItemBoard";
import { PackageChecks } from "./Packages";
import { LegendLine, STATE_GLYPH, StateChip, stateLabel } from "./states";
import { itemLabel } from "../state/caption";

const FINAL = ["kept", "repaired", "rolled_back"];
const COUNT_ORDER = ["investigating", "in_package", "kept", "repaired", "rolled_back", "safe", "candidate", "suggest", "dropped", "skipped"];

export interface ProjectFiles {
  files: FileEntry[];
  complete: boolean;
}

export function useProjectFiles(root: string, path: string) {
  return useApi<ProjectFiles>(`files:${root}/${path}`, () => api("/api/run/files", { root, path }));
}

// The saved file list, or the files the events name when the run saved none.
export function treeFiles(saved: ProjectFiles | null, events: StudioEvent[]): FileEntry[] {
  if (saved?.complete) return saved.files;
  return filesFromEvents(events).map((path) => ({ path, lines: null }));
}

// The tree's key of a candidate: a class, function or line range sits under its file.
export function itemKey(unit: string): string {
  return unit.includes("::") ? `unit:${unit}` : `file:${unit}`;
}

function Counts({ counts }: { counts: Record<string, number> }) {
  const shown = COUNT_ORDER.filter((s) => counts[s]);
  if (!shown.length) return null;
  return (
    <span className="tree-counts">
      {shown.map((s) => (
        <span key={s} className={`tree-count st-${s}`}>
          {/* a thin space keeps "○ 14" from reading as "014" */}
          <span aria-hidden>
            {STATE_GLYPH[s]}
            {" "}
            {counts[s]}
          </span>
          <span className="sr-only">
            , {counts[s]} {stateLabel(s)}
          </span>
        </span>
      ))}
    </span>
  );
}

export function TreeRow({
  node,
  depth,
  open,
  selected,
  onToggle,
  onSelect,
  atWork = false,
}: {
  node: TreeNode;
  depth: number;
  open: boolean;
  selected: boolean;
  onToggle: () => void;
  onSelect: () => void;
  atWork?: boolean;
}) {
  const parent = node.children.length > 0;
  // the row's name is its text: the name, then (for screen readers) its state and last agent
  const said = `: ${stateLabel(node.state)}${node.actor ? `, last ${agentName(node.actor)}` : ""}`;
  return (
    <div
      className={`tree-row kind-${node.kind} st-${node.state} ${selected ? "selected" : ""} ${node.focus ? "focus" : ""} ${atWork ? "at-work" : ""}`}
      style={{ paddingLeft: `calc(${depth} * var(--tree-indent))` }}
      data-key={node.key}
    >
      {/* the arrow keys open and close a row; the caret is for the mouse */}
      <span className={`tree-caret ${parent ? "parent" : ""}`} onClick={parent ? onToggle : undefined} aria-hidden>
        {parent ? (open ? "▾" : "▸") : ""}
      </span>
      <button
        className="tree-label"
        onClick={onSelect}
        role="treeitem"
        aria-selected={selected}
        aria-expanded={parent ? open : undefined}
        title={node.path || node.name}
      >
        <span className="state-glyph" aria-hidden>
          {STATE_GLYPH[node.state] || ""}
        </span>
        <span className="tree-name">{node.name}</span>
        <span className="sr-only">{said}</span>
        {atWork && (
          <span className="tree-state" aria-hidden>
            {stateLabel(node.state)}
          </span>
        )}
        {node.kind === "file" && node.lines !== null && (
          <span className="tree-lines">
            <span className="sr-only">, </span>
            {node.lines} lines
          </span>
        )}
        {(node.kind === "folder" || node.kind === "file") && <Counts counts={node.counts} />}
        {node.actor && <AgentIcon agent={node.actor} />}
      </button>
    </div>
  );
}

function ItemDiff({ item, path, state, detail }: { item: Item; path: string; state: RunState; detail: RunDetail | null }) {
  const run = useContext(RunContext);
  const pkg = item.pkg ? state.packages[item.pkg] : null;
  const ids = pkg && detail?.has_cache ? pkg.diffs : [];
  const result = FINAL.includes(item.stage) ? detail?.report?.results.find((r) => r.item_id === item.id && r.diff) : null;
  if (ids.length && run) return <>{ids.map((id) => <ArtifactDiff key={id} id={id} path={path} />)}</>;
  if (result) return <DiffView text={result.diff} maxHeight={360} />;
  if (!pkg) return <Empty>Not in a work package{item.stage === "suggest" ? ": reported as a suggestion, not applied" : " yet"}.</Empty>;
  return <Empty>{pkg.diffs.length ? "This recording has no diff for it." : "Not applied yet."}</Empty>;
}

function ArtifactDiff({ id, path }: { id: string; path: string }) {
  const run = useContext(RunContext)!;
  const res = useApi<{ text?: string }>(`${run.root}/${run.path}/${id}`, () => api("/api/run/artifact", { root: run.root, path: run.path, id }));
  if (res.loading) return <Loading what="Loading the diff" />;
  if (res.error) return <Empty>The diff is not in this recording.</Empty>;
  return <DiffView text={filterDiff(res.data?.text || "", path)} maxHeight={360} />;
}

function NodeDetail({ node, state, detail, onPick }: { node: TreeNode; state: RunState; detail: RunDetail | null; onPick: (key: string) => void }) {
  const own = node.own.map((id) => state.items[id]);
  const below = node.items.filter((id) => !node.own.includes(id)).map((id) => state.items[id]);
  return (
    <div className="node-detail" aria-label="Details">
      <header className="node-head">
        <h3>
          <span className={`st-${node.state}`}>
            <span className="state-glyph" aria-hidden>
              {STATE_GLYPH[node.state]}
            </span>
          </span>{" "}
          <code>{node.kind === "folder" || node.kind === "file" ? node.path || node.name : `${node.path} · ${node.name}`}</code>
        </h3>
        <StateChip state={node.state} />
        {node.actor && (
          <span className="muted small">
            last: <AgentTag agent={node.actor} />
          </span>
        )}
      </header>
      {!node.items.length && <Empty>No detector flagged anything here.</Empty>}
      {own.map((item) => (
        <section key={item.id} className="node-item">
          <h4>
            {item.category.replace(/_/g, " ")} · {item.lane} lane
          </h4>
          <ItemDetail item={item} state={state} />
          <h4>Diff</h4>
          <ItemDiff item={item} path={node.path} state={state} detail={detail} />
          <h4>Checks</h4>
          {item.pkg && state.packages[item.pkg] ? (
            <PackageChecks pkg={state.packages[item.pkg]} />
          ) : (
            <Empty>No checks: only items in a work package are applied and checked.</Empty>
          )}
        </section>
      ))}
      {below.length > 0 && (
        <>
          <h4>Candidates in here ({below.length})</h4>
          <ul className="node-items">
            {below.map((item) => {
              const key = itemKey(item.unit);
              return (
                <li key={item.id}>
                  <button className="link" onClick={() => onPick(key)}>
                    <code>{item.unit}</code>
                  </button>{" "}
                  <StateChip state={item.stage} /> <span className="muted small">{item.category.replace(/_/g, " ")}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

// The height left under the cards' top edge (in a window scrolled to the top), so the tree and
// its details fit on the screen and scroll only inside themselves.
function useFitHeight(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(480);
  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top + window.scrollY;
      setHeight(Math.max(240, window.innerHeight - top - 16));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  return [ref, height];
}

export type TreeView = ReturnType<typeof useTreeView>;

// Which nodes are open; with `follow`, the latest action is opened and scrolled into view
// (inside the tree's own box, never the page).
export function useTreeView(tree: TreeNode, follow: boolean, count: number) {
  const [open, setOpen] = useState<Set<string> | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);
  const expanded = open ?? defaultExpanded(tree);
  const path = focusPath(tree).join(",");
  useEffect(() => {
    if (!follow || !path) return;
    setOpen((o) => new Set([...(o ?? defaultExpanded(tree)), ...path.split(",")]));
  }, [follow, path]);
  useEffect(() => {
    const row = treeRef.current?.querySelector(".tree-row.at-work") ?? treeRef.current?.querySelector(".tree-row.focus:not(.kind-folder)");
    const box = treeRef.current?.parentElement;
    if (!follow || !row || !box) return;
    // the row goes to the middle of the tree's own box; the page itself never scrolls
    const r = row.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    box.scrollTop += r.top + r.height / 2 - (b.top + b.height / 2);
  }, [follow, count, open]);
  const rows = visibleRows(tree, expanded);
  const toggle = (key: string) => {
    const next = new Set(expanded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setOpen(next);
  };
  // arrow keys move between rows and open or close them
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const buttons = [...(treeRef.current?.querySelectorAll<HTMLButtonElement>(".tree-label") || [])];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    const row = rows[at];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      buttons[Math.max(0, Math.min(buttons.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
    } else if ((e.key === "ArrowRight" && !expanded.has(row.node.key)) || (e.key === "ArrowLeft" && expanded.has(row.node.key))) {
      if (row.node.children.length) toggle(row.node.key);
    } else return;
    e.preventDefault();
  };
  return { expanded, setOpen, rows, toggle, onKey, treeRef };
}

export function TreeList({ view, chosen, onSelect, atWork }: { view: TreeView; chosen: string | null; onSelect: (key: string) => void; atWork?: string | null }) {
  return (
    <div className="tree" role="tree" aria-label="Project tree" ref={view.treeRef} onKeyDown={view.onKey}>
      {view.rows.map(({ node: n, depth }) => (
        <TreeRow
          key={n.key}
          node={n}
          depth={depth}
          open={view.expanded.has(n.key)}
          selected={n.key === chosen}
          onToggle={() => view.toggle(n.key)}
          onSelect={() => (chosen === n.key && n.children.length ? view.toggle(n.key) : onSelect(n.key))}
          atWork={n.key === atWork}
        />
      ))}
    </div>
  );
}

export function ProjectView({
  state,
  events,
  detail,
  files,
}: {
  state: RunState;
  events: StudioEvent[];
  detail: RunDetail;
  files: ProjectFiles | null;
}) {
  const list = useMemo(() => treeFiles(files, events), [files, events.length]);
  const name = (state.repo || detail.target || "project").replace(/^local:/, "");
  const tree = useMemo(() => buildTree(list, state, name), [list, state]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const view = useTreeView(tree, follow, state.count);
  const [fit, height] = useFitHeight();
  const node = chosen ? findNode(tree, chosen) : null;
  const pick = (key: string) => {
    setChosen(key);
    view.setOpen(new Set([...view.expanded, ...pathTo(tree, key)]));
  };
  const py = list.filter((f) => f.path.endsWith(".py")).length;
  const focusItem = state.focus.length ? state.items[state.focus[0]] : null;
  return (
    <div className="project-view">
      <div className="project" ref={fit} style={{ ["--fit" as string]: `${height}px` }}>
        <Card
          title={
            <>
              Project files{" "}
              {/* a run without a file list: the tree has the files its events name, said in the tooltip */}
              <span
                className="muted small"
                title={
                  files && !files.complete
                    ? `This run saved no file list, so the tree shows the ${list.length} files its events name${state.facts?.python_files ? ` (${py} of the ${state.facts.python_files} Python files the Explorer counted)` : ""}.`
                    : undefined
                }
              >
                {list.length} files
              </span>
            </>
          }
          actions={
            <label className="check follow">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow the action
            </label>
          }
          className="tree-card"
        >
          <LegendLine />
          {!view.rows.length ? (
            <Empty>No files yet: the Explorer lists them when the run starts.</Empty>
          ) : (
            <TreeList view={view} chosen={chosen} onSelect={setChosen} atWork={focusItem ? itemKey(focusItem.unit) : null} />
          )}
        </Card>
        <Card className="detail-card">
          {node ? (
            <NodeDetail node={node} state={state} detail={detail} onPick={pick} />
          ) : (
            <div className="node-empty">
              {focusItem ? (
                <>
                  <p className="now">
                    Now: <AgentTag agent={focusItem.actor || state.active || "manager"} /> on{" "}
                    <button className="link" onClick={() => pick(itemKey(focusItem.unit))} title={focusItem.unit}>
                      {itemLabel(focusItem)}
                    </button>
                  </p>
                  {/* following the action: the latest decision on the item at work, the rest behind "Show details" */}
                  {follow && <Pointer note={{ items: [focusItem.id], match: "exact" }} state={state} brief />}
                </>
              ) : (
                <p>Click a file, class or function to see its evidence chain, its diff and the checks it passed.</p>
              )}
              <p className="muted small">Click any file or function for its diff.</p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
