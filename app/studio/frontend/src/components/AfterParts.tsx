import { useMemo, type ReactNode } from "react";
import { annotateFile, categoryLabel, decisionSteps, packageChecks, type HunkNote } from "../state/annotate";
import type { FileTree, Metrics, Pair } from "../state/beforeAfter";
import type { DiffFile } from "../state/diff";
import type { RunState } from "../state/fold";
import { AgentTag } from "./AgentIcon";
import { Card, Empty, Status } from "./common";
import { SideBySide } from "./SideBySide";
import { StateChip } from "./states";

// The pieces of before / after that the screen, presentation mode and the exported report share.
export const SMALL = 60;

function num(v: number | null): string {
  return v === null ? "?" : v.toLocaleString();
}

// One headline number before and after, with its change: green when it moved the right way.
function Figure({ label, pair, fewer, note }: { label: string; pair: Pair; fewer: boolean; note?: string }) {
  const delta = pair.before !== null && pair.after !== null ? pair.after - pair.before : null;
  const good = delta !== null && delta !== 0 && (fewer ? delta < 0 : delta > 0);
  const bad = delta !== null && delta !== 0 && !good;
  return (
    <div className="ba-figure">
      {pair.before === null && pair.after === null ? (
        <div className="ba-numbers muted">not recorded</div>
      ) : (
        <div className="ba-numbers">
          <span className="ba-pair">
            <b>{num(pair.before)}</b> <span className="arrow">→</span> <b>{num(pair.after)}</b>
          </span>
          {delta !== null && (
            <span className={`delta ${good ? "good-text" : bad ? "bad-text" : "muted"}`}>{delta === 0 ? "no change" : delta > 0 ? `+${delta}` : `−${-delta}`}</span>
          )}
        </div>
      )}
      <div className="ba-label">
        {label}
        {note && <span className="muted"> · {note}</span>}
      </div>
    </div>
  );
}

// The four numbers that say how the project changed, across the whole width.
export function HeadlineBand({ m }: { m: Metrics }) {
  const loc = `non-test Python${m.loc.source === "hidden checks" ? ", hidden checks" : ""}; diff −${m.linesRemoved} +${m.linesAdded}`;
  return (
    <div className="ba-band">
      <Figure label="Lines of code" pair={m.loc} fewer note={m.loc.source ? loc : undefined} />
      <Figure label="Files" pair={m.files} fewer />
      <Figure label="Python files" pair={m.pyFiles} fewer />
      <Figure label="Tests passing" pair={m.tests ? m.tests.passed : { before: null, after: null }} fewer={false} />
    </div>
  );
}

// Everything else about the result: the verdict, the tests, the probes, the public names, the
// slop by category, and what no check can see.
export function DetailsCard({ m }: { m: Metrics }) {
  const shortName = (unit: string) => unit.split("::").pop();
  return (
    <Card title="The result" className="metrics-card">
      <dl className="ba-metrics">
        <dt>Result</dt>
        <dd>{m.finished ? <Status value={m.verdict} /> : <Status value="in progress" />}</dd>
        <dt>Tests</dt>
        <dd>
          {m.tests ? (
            <>
              failing before {m.tests.failing} · new failures <b className={m.tests.newFailures.length ? "bad-text" : ""}>{m.tests.newFailures.length}</b> · flaky{" "}
              {m.tests.flaky}
              <span className="muted small"> (baseline, 3 runs)</span>
              {m.tests.removed.length > 0 && <div className="small warn-text">tests in removed files: {m.tests.removed.join(", ")}</div>}
            </>
          ) : (
            <span className="muted">no baseline</span>
          )}
        </dd>
        <dt>Probes</dt>
        <dd>
          <b>{m.probes.cases}</b> cases ·{" "}
          {m.probes.coverage === null ? (
            <span className="muted">no changed lines to cover in the kept packages</span>
          ) : (
            <>
              coverage of the changed lines <b>{Math.round(m.probes.coverage * 100)}%</b>
              <span className="muted small">
                {" "}
                ({m.probes.measured} of {m.probes.packages} kept packages had lines to cover)
              </span>
            </>
          )}
        </dd>
        <dt>Public names</dt>
        <dd>
          {m.publicApi.removed.length ? (
            <span className="warn-text">
              {m.publicApi.removed.length} removed: {m.publicApi.removed.map(shortName).join(", ")}
            </span>
          ) : (
            <span>unchanged</span>
          )}
          <span className="muted small"> ({m.publicApi.checked} kept packages checked)</span>
        </dd>
      </dl>
      <table className="data slop-table" aria-label="Slop by category">
        <thead>
          <tr>
            <th>Slop by category</th>
            <th className="num">Found</th>
            <th className="num">Left</th>
          </tr>
        </thead>
        <tbody>
          {m.slop.map((s) => (
            <tr key={s.category}>
              <td>{categoryLabel(s.category)}</td>
              <td className="num">{s.before}</td>
              <td className="num">
                {s.after}
                {s.after < s.before && <span className="muted"> (−{s.before - s.after})</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="honest">Behavior that nothing tests isn't covered: the tests and the probes check only the code they run.</p>
    </Card>
  );
}

// The top of before / after: the headline band, then both trees and the details in columns of
// one height.
export function AfterTop({ m, before, after }: { m: Metrics; before: ReactNode; after: ReactNode }) {
  return (
    <section className="ba-summary" aria-label="Before and after">
      <HeadlineBand m={m} />
      <div className="ba-top">
        {before}
        {after}
        <DetailsCard m={m} />
      </div>
    </section>
  );
}

function changedOnly(n: FileTree): FileTree | null {
  if (n.kind === "file") return n.status === "unchanged" ? null : n;
  const children = n.children.map(changedOnly).filter((c): c is FileTree => c !== null);
  return children.length ? { ...n, children } : null;
}

function TreeLines({ node, depth, selected, onSelect }: { node: FileTree; depth: number; selected: string; onSelect: (path: string) => void }) {
  return (
    <>
      {node.children.map((c) => (
        <div key={c.key}>
          <button
            className={`ba-row ${c.kind} ba-${c.status} ${c.path === selected ? "selected" : ""}`}
            style={{ paddingLeft: `calc(${depth} * 16px + 4px)` }}
            onClick={() => c.kind === "file" && c.status !== "unchanged" && onSelect(c.path)}
            disabled={c.kind === "folder" || c.status === "unchanged"}
            title={c.path}
          >
            <span className="ba-name">{c.status === "removed" || c.status === "gone" ? <del>{c.name}</del> : c.name}</span>
            {c.status === "removed" && <span className="ba-tag bad-text">removed</span>}
            {c.status === "gone" && <span className="ba-tag bad-text">folder removed</span>}
            {c.status === "added" && <span className="ba-tag good-text">new</span>}
            {c.status === "edited" && c.kind === "file" && (
              <span className="ba-tag">
                {c.added > 0 && <span className="added">+{c.added}</span>} {c.removed > 0 && <span className="removed">−{c.removed}</span>}
              </span>
            )}
            {c.status === "unchanged" && c.kind === "file" && c.lines !== null && <span className="ba-tag muted">{c.lines}</span>}
          </button>
          {c.kind === "folder" && <TreeLines node={c} depth={depth + 1} selected={selected} onSelect={onSelect} />}
        </div>
      ))}
    </>
  );
}

export function TreeCard({ title, tree, selected, onSelect, all }: { title: string; tree: FileTree; selected: string; onSelect: (p: string) => void; all: boolean }) {
  const shown = all ? tree : changedOnly(tree);
  return (
    <Card title={title} className="ba-tree">
      <div aria-label={`${title} tree`} role="group">
        {shown ? <TreeLines node={shown} depth={0} selected={selected} onSelect={onSelect} /> : <Empty>No files changed.</Empty>}
      </div>
    </Card>
  );
}

export function Pointer({ note, state, n = 0 }: { note: HunkNote; state: RunState; n?: number }) {
  const marker = n > 0 && (
    <span className="pointer-n" aria-hidden>
      {n}
    </span>
  );
  if (!note.items.length) {
    return (
      <div className="pointer">
        {marker}
        Not tied to a candidate: no applied candidate is in this file.
      </div>
    );
  }
  return (
    <div className={`pointer st-${state.items[note.items[0]].stage}`}>
      {marker}
      {note.match !== "exact" && (
        <p className="small muted">
          {note.match === "only" ? "The only candidate applied in this file:" : "The hunk names none of this file's applied candidates; they are:"}
        </p>
      )}
      {note.items.map((id) => {
        const item = state.items[id];
        const pkg = item.pkg ? state.packages[item.pkg] : null;
        return (
          <div key={id} className="pointer-item">
            <div className="pointer-head">
              <span className="category-chip">{categoryLabel(item.category)}</span>
              <code>{item.unit.split("::").pop()}</code>
              <StateChip state={item.stage} />
              {pkg && <span className="muted small">{pkg.id}</span>}
            </div>
            <div className="pointer-body">
              <div>
                <h4>Decisions</h4>
                <ol className="steps">
                  {decisionSteps(item, state).map((s, i) => (
                    <li key={i}>
                      <AgentTag agent={s.agent} /> {s.text}
                    </li>
                  ))}
                </ol>
              </div>
              <div>
                <h4>Evidence</h4>
                {item.verdict?.evidence.length ? (
                  <ul className="evidence">
                    {item.verdict.evidence.map((ev: any, i: number) => (
                      <li key={i}>
                        {typeof ev === "string" ? ev : (
                          <>
                            {ev.tool && <code>{ev.tool}</code>} {ev.says || ev.result}
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted small">No evidence listed (decided by its detector's rule).</p>
                )}
                <h4>Checks</h4>
                {pkg ? (
                  <ul className="checks-list">
                    {packageChecks(pkg).map((c, i) => (
                      <li key={i} className={c.ok === true ? "ok" : c.ok === false ? "fail" : "info"}>
                        <span aria-hidden>{c.ok === true ? "✓" : c.ok === false ? "✗" : "·"}</span> {c.label}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted small">Not in a work package.</p>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function FileDiff({ file, state }: { file: DiffFile; state: RunState }) {
  const notes = useMemo(() => annotateFile(file, state), [file, state]);
  const whole = file.status === "removed" || file.status === "added";
  return (
    <Card
      title={
        <>
          <code>{file.path}</code> {file.added > 0 && <span className="added">+{file.added}</span>}{" "}
          {file.removed > 0 && <span className="removed">−{file.removed}</span>}{" "}
          <span className="muted small">{file.status === "removed" ? "file removed" : file.status === "added" ? "new file" : file.status}</span>
        </>
      }
      className="file-diff"
    >
      {file.status === "renamed" && <p>Renamed from <code>{file.oldPath}</code>.</p>}
      {file.hunks.map((hunk, i) => (
        <section key={i} className="hunk" aria-label={`change ${i + 1} of ${file.hunks.length}`}>
          <Pointer note={notes[i]} state={state} n={file.hunks.length > 1 ? i + 1 : 0} />
          {whole ? (
            <details>
              <summary>
                {file.status === "removed" ? `Show the ${hunk.oldCount} removed lines` : `Show the ${hunk.newCount} new lines`}
              </summary>
              <SideBySide hunk={hunk} path={file.path} only={file.status === "removed" ? "left" : "right"} />
            </details>
          ) : (
            <SideBySide hunk={hunk} path={file.path} />
          )}
        </section>
      ))}
    </Card>
  );
}

