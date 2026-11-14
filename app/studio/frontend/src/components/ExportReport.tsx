import { renderToStaticMarkup } from "react-dom/server";
import css from "../styles.css?raw";
import type { AfterModel } from "../state/beforeAfter";
import { itemLabel } from "../state/caption";
import { buildTree, type TreeNode } from "../state/tree";
import { AfterTop, FileDiff, SMALL, TreeCard } from "./AfterParts";
import { categoryLabel } from "../state/annotate";
import { STATE_GLYPH, StateChip, StateLegend, stateLabel } from "./states";

export interface ExportRun {
  name: string;
  target: string | null;
  mode: string | null;
  model: string | null;
  started: string | null;
}

// The run's candidates on its file tree, every node open, as a plain nested list.
function StaticTree({ node }: { node: TreeNode }) {
  return (
    <ul className="static-tree">
      {node.children.map((c) => (
        <li key={c.key} className={`st-${c.state}`}>
          <span className="state-glyph" aria-hidden>
            {STATE_GLYPH[c.state] || ""}
          </span>{" "}
          <span className={`static-name kind-${c.kind}`}>{c.name}</span>
          {c.own.length > 0 && <span className="static-state"> {stateLabel(c.state)}</span>}
          {c.children.length > 0 && <StaticTree node={c} />}
        </li>
      ))}
    </ul>
  );
}

export function ExportReport({ model, run }: { model: AfterModel; run: ExportRun }) {
  const { state, parsed, trees, m, list } = model;
  const tree = buildTree(list, state, model.name);
  const suggestions = state.itemOrder.map((id) => state.items[id]).filter((i) => i.stage === "suggest");
  const judged = state.model
    ? `The Investigators' verdicts came from the model ${state.model} (LLM-judged); the tests and probes decided what was kept.`
    : "No LLM was used: the agents decided by rules, and the tests and probes decided what was kept.";
  return (
    <article className="export">
      <header className="export-head">
        <h1>CleanSweep cleanup: {model.name}</h1>
        <p className="muted">
          {[run.name, run.target, run.mode && `${run.mode} mode`, `model ${run.model || "none"}`, run.started].filter(Boolean).join(" · ")}
        </p>
        <p className="export-verdict">
          Result: <StateChip state={m.verdict === "everything runs" ? "kept" : "untouched"} label={m.verdict || "not finished"} />
        </p>
      </header>
      <AfterTop
        m={m}
        before={<TreeCard title="Before" tree={trees.before} selected="" onSelect={() => undefined} all={list.length <= SMALL} />}
        after={<TreeCard title="After" tree={trees.after} selected="" onSelect={() => undefined} all={list.length <= SMALL} />}
      />
      <h2>Every change, with the decisions behind it</h2>
      {parsed.length ? parsed.map((f) => <FileDiff key={f.path} file={f} state={state} />) : <p className="muted">No changes: nothing was applied.</p>}
      <h2>Left for a person ({suggestions.length})</h2>
      {suggestions.length ? (
        <table className="data">
          <thead>
            <tr>
              <th>candidate</th>
              <th>category</th>
              <th>why it was not applied</th>
            </tr>
          </thead>
          <tbody>
            {suggestions.map((i) => (
              <tr key={i.id}>
                <td>
                  <code>{itemLabel(i)}</code>
                </td>
                <td>{categoryLabel(i.category)}</td>
                <td>{i.verdict?.reason || `${i.lane} lane`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">None.</p>
      )}
      <h2>The project tree: every candidate's last state</h2>
      <StateLegend />
      <StaticTree node={tree} />
      <footer className="export-foot">
        <p>{judged}</p>
        <p>Behavior that nothing tests isn't covered: the tests and the probes check only the code they run.</p>
        <p className="muted small">Made by CleanSweep Studio from the run's events and saved outputs. This file needs no network.</p>
      </footer>
    </article>
  );
}

function escape(text: string): string {
  return text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

const EXPORT_CSS = `
body { padding: var(--space-5); }
.export { max-width: 1180px; margin: 0 auto; }
.export h1 { font-size: var(--text-xl); margin: 0; }
.export h2 { font-size: var(--text-lg); margin: var(--space-5) 0 var(--space-2); }
.export .ba-row { cursor: default; }
.export .ba-tree .card-body { max-height: none; }
.export-verdict { font-size: var(--text-lg); }
.static-tree { list-style: none; margin: 0; padding-left: var(--space-4); font-size: var(--text-sm); }
.static-name { font-family: var(--mono); }
.static-name.kind-folder { font-family: var(--font); font-weight: 700; }
.static-tree li:not(.st-untouched) > .static-name { color: var(--st); font-weight: 600; }
.static-state { color: var(--st); font-size: var(--text-xs); }
.export-foot { margin-top: var(--space-5); border-top: 1px solid var(--border); padding-top: var(--space-3); }
@media print { .card { break-inside: avoid; } body { padding: 0; } }
`;

// A self-contained HTML page: the styles inline, no scripts, no links out.
export function exportHtml(model: AfterModel, run: ExportRun): string {
  const body = renderToStaticMarkup(<ExportReport model={model} run={run} />);
  const title = escape(`CleanSweep cleanup: ${model.name}`);
  return `<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>${css}${EXPORT_CSS}</style>
</head>
<body>
${body}
</body>
</html>
`;
}

export function downloadHtml(html: string, name: string): void {
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
