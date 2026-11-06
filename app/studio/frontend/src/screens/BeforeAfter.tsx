import { useEffect, useMemo, useRef, useState } from "react";
import { afterHash, api, runHash, useApi, type RunDetail } from "../api";
import { AgentIcon, AgentTag, agentName } from "../components/AgentIcon";
import { PresentShell } from "../components/PresentShell";
import { Async, Card, Empty, ErrorBox, Loading, Status } from "../components/common";
import { treeFiles, useProjectFiles } from "../components/ProjectView";
import { SideBySide } from "../components/SideBySide";
import { StateChip } from "../components/states";
import { annotateFile, categoryLabel, decisionSteps, packageChecks, type HunkNote } from "../state/annotate";
import { fileStats, fileTrees, metrics, type FileTree, type Metrics, type Pair } from "../state/beforeAfter";
import { parseDiff, type DiffFile } from "../state/diff";
import { itemLabel } from "../state/caption";
import { fold, type Item, type RunState, type StudioEvent } from "../state/fold";
import { SLIDE_MS, afterSlides, type Slide } from "../state/present";
import { useEvents } from "../state/hooks";

const SMALL = 60;

function num(v: number | null): string {
  return v === null ? "?" : v.toLocaleString();
}

function Change({ pair, unit = "" }: { pair: Pair; unit?: string }) {
  if (pair.before === null && pair.after === null) return <span className="muted">not recorded</span>;
  const delta = pair.before !== null && pair.after !== null ? pair.after - pair.before : null;
  return (
    <span className="change">
      <b>{num(pair.before)}</b> <span className="arrow">→</span> <b>{num(pair.after)}</b>
      {unit}
      {delta !== null && delta !== 0 && <span className="delta">{delta > 0 ? `+${delta}` : `−${-delta}`}</span>}
    </span>
  );
}

function MetricsCard({ m }: { m: Metrics }) {
  const shortName = (unit: string) => unit.split("::").pop();
  return (
    <Card title="Before → after" className="metrics-card">
      <dl className="ba-metrics" aria-label="Before and after">
        <dt>Result</dt>
        <dd>{m.finished ? <Status value={m.verdict} /> : <Status value="in progress" />}</dd>
        <dt>Files</dt>
        <dd>
          <Change pair={m.files} />
        </dd>
        <dt>Python files</dt>
        <dd>
          <Change pair={m.pyFiles} />
        </dd>
        <dt title="lines in Python files outside the tests">Lines of code</dt>
        <dd>
          <Change pair={m.loc} />
          {m.loc.source && <span className="muted small"> (non-test Python{m.loc.source === "hidden checks" ? ", hidden checks" : ""})</span>}
          <span className="muted small">
            {" "}
            diff: −{m.linesRemoved} +{m.linesAdded}
          </span>
        </dd>
        <dt>Tests passing</dt>
        <dd>
          {m.tests ? (
            <>
              <Change pair={m.tests.passed} />
              <span className="small">
                {" "}
                · failing before {m.tests.failing} · new failures <b className={m.tests.newFailures.length ? "bad-text" : ""}>{m.tests.newFailures.length}</b> · flaky {m.tests.flaky}
                <span className="muted"> (baseline, 3 runs)</span>
              </span>
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
            <th>slop by category</th>
            <th>found</th>
            <th>left</th>
          </tr>
        </thead>
        <tbody>
          {m.slop.map((s) => (
            <tr key={s.category}>
              <td>{categoryLabel(s.category)}</td>
              <td>{s.before}</td>
              <td>
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

function TreeCard({ title, tree, selected, onSelect, all }: { title: string; tree: FileTree; selected: string; onSelect: (p: string) => void; all: boolean }) {
  const shown = all ? tree : changedOnly(tree);
  return (
    <Card title={title} className="ba-tree">
      <div aria-label={`${title} tree`} role="group">
        {shown ? <TreeLines node={shown} depth={0} selected={selected} onSelect={onSelect} /> : <Empty>No files changed.</Empty>}
      </div>
    </Card>
  );
}

function Pointer({ note, state }: { note: HunkNote; state: RunState }) {
  if (!note.items.length) return <div className="pointer">Not tied to a candidate: no applied candidate is in this file.</div>;
  return (
    <div className="pointer">
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

function FileDiff({ file, state }: { file: DiffFile; state: RunState }) {
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
          <Pointer note={notes[i]} state={state} />
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

// Everything both views draw: the folded run, the parsed diff, both trees and the numbers.
function useAfterModel(detail: RunDetail, events: StudioEvent[], diff: string) {
  const files = useProjectFiles(detail.root, detail.path);
  const state = useMemo(() => fold(events), [events]);
  const parsed = useMemo(() => parseDiff(diff), [diff]);
  const list = useMemo(() => treeFiles(files.data, events), [files.data, events]);
  const stats = useMemo(() => fileStats(list, parsed), [list, parsed]);
  const name = (state.repo || detail.target || "project").replace(/^local:/, "");
  const trees = useMemo(() => fileTrees(stats, name), [stats, name]);
  const m = useMemo(() => metrics(state, stats, Boolean(files.data?.complete), detail.report?.stats), [state, stats, files.data, detail]);
  return { files, state, parsed, list, trees, m, name };
}

function View({ detail, events, diff }: { detail: RunDetail; events: StudioEvent[]; diff: string }) {
  const { files, state, parsed, list, trees, m } = useAfterModel(detail, events, diff);
  const [chosen, setChosen] = useState("");
  const [all, setAll] = useState<boolean | null>(null);
  const diffRef = useRef<HTMLDivElement>(null);
  const showAll = all ?? list.length <= SMALL;
  const file = parsed.find((f) => f.path === chosen) || parsed[0];
  const pick = (path: string) => {
    setChosen(path);
    diffRef.current?.scrollIntoView({ block: "start" });
  };
  useEffect(() => setChosen(""), [diff]);
  if (files.loading && !files.data) return <Loading what="Loading the file list" />;
  return (
    <>
      {!state.finished && <div className="live-banner">The run hasn't finished: this is what it has applied so far.</div>}
      {files.data && !files.data.complete && (
        <p className="tree-note small">
          This run saved no file list: the trees show the {list.length} files its events and diff name. Unchanged files it never
          mentions are not shown.
        </p>
      )}
      <div className="ba-top">
        <TreeCard title="Before" tree={trees.before} selected={file?.path || ""} onSelect={pick} all={showAll} />
        <TreeCard title="After" tree={trees.after} selected={file?.path || ""} onSelect={pick} all={showAll} />
        <MetricsCard m={m} />
      </div>
      <div className="ba-tools">
        <label className="check">
          <input type="checkbox" checked={showAll} onChange={(e) => setAll(e.target.checked)} /> Show unchanged files
        </label>
        {trees.gone.length > 0 && <span className="small">Folders removed: {trees.gone.join(", ")}</span>}
        <span className="small muted">Click a changed file for its diff, each change with the decisions behind it.</span>
      </div>
      <div ref={diffRef}>{file ? <FileDiff key={file.path} file={file} state={state} /> : <Empty>No changes: nothing was applied.</Empty>}</div>
    </>
  );
}

function Chain({ item, state }: { item: Item; state: RunState }) {
  return (
    <ol className="chain-strip" aria-label="Decisions">
      {decisionSteps(item, state).map((s, i) => (
        <li key={i} title={s.text}>
          <AgentIcon agent={s.agent} />
          <span>
            <b>{agentName(s.agent)}</b> {s.brief}
          </span>
        </li>
      ))}
    </ol>
  );
}

function ChangeSlide({ slide, state }: { slide: Extract<Slide, { kind: "change" }>; state: RunState }) {
  const items = slide.note.items.map((id) => state.items[id]);
  const main = items[0];
  const pkg = main?.pkg ? state.packages[main.pkg] : null;
  const removed = slide.file.status === "removed";
  return (
    <div className="change-slide">
      <div className="caption" aria-label="Caption">
        {main && <span className="category-chip">{categoryLabel(main.category)}</span>}
        <p>
          {main ? <code>{itemLabel(main)}</code> : "A change"} {removed ? "deleted" : "in"} <code>{slide.file.path}</code>
          {items.length > 1 && <span className="muted"> (and {items.length - 1} more)</span>}
        </p>
        {main && <StateChip state={main.stage} />}
      </div>
      <p className="caption-detail">{main?.verdict?.reason || (slide.note.match === "none" ? "No applied candidate is in this file." : " ")}</p>
      {main && <Chain item={main} state={state} />}
      <div className="slide-diff">
        <SideBySide hunk={slide.file.hunks[slide.hunk]} path={slide.file.path} only={removed ? "left" : slide.file.status === "added" ? "right" : undefined} />
      </div>
      {pkg && (
        <ul className="check-chips" aria-label="Checks">
          {packageChecks(pkg).map((c, i) => (
            <li key={i} className={c.ok === true ? "ok" : c.ok === false ? "fail" : "info"}>
              <span aria-hidden>{c.ok === true ? "✓" : c.ok === false ? "✗" : "·"}</span> {c.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PresentAfter({ detail, events, diff }: { detail: RunDetail; events: StudioEvent[]; diff: string }) {
  const { state, parsed, trees, m, name } = useAfterModel(detail, events, diff);
  const slides = useMemo(() => afterSlides(parsed, state), [parsed, state]);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const go = (k: number) => setAt(Math.max(0, Math.min(slides.length - 1, k)));
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setAt((a) => {
        if (a >= slides.length - 1) {
          setPlaying(false);
          return a;
        }
        return a + 1;
      });
    }, SLIDE_MS);
    return () => clearInterval(timer);
  }, [playing, slides.length]);
  const slide = slides[Math.min(at, slides.length - 1)];
  const changes = slides.length - 2;
  return (
    <PresentShell
      title={`Before / after: ${name}`}
      position={slide.kind === "change" ? `change ${slide.n} of ${slide.of}` : `${changes} changes`}
      progress={slides.length > 1 ? at / (slides.length - 1) : 1}
      playing={playing}
      onPlay={() => {
        if (at >= slides.length - 1) setAt(0);
        setPlaying(!playing);
      }}
      onNext={() => go(at + 1)}
      onPrev={() => go(at - 1)}
      exit={afterHash(detail)}
      nextLabel="Next change"
    >
      {slide.kind === "summary" ? (
        <div className="summary-slide">
          <div className="caption" aria-label="Caption">
            <p>
              {slide.first ? `${changes} changes, each one checked before it was kept.` : "That is the whole cleanup."} Result: <b>{m.verdict || "not finished"}</b>
            </p>
          </div>
          <p className="caption-detail">Behavior that nothing tests isn't covered: the tests and the probes check only the code they run.</p>
          <div className="ba-top">
            <TreeCard title="Before" tree={trees.before} selected="" onSelect={() => undefined} all={false} />
            <TreeCard title="After" tree={trees.after} selected="" onSelect={() => undefined} all={false} />
            <MetricsCard m={m} />
          </div>
        </div>
      ) : (
        <ChangeSlide key={at} slide={slide} state={state} />
      )}
    </PresentShell>
  );
}

export function BeforeAfter({ root, path, present = false }: { root: string; path: string; present?: boolean }) {
  const res = useApi<RunDetail>(`${root}/${path}`, () => api("/api/run", { root, path }));
  const diff = useApi<{ text: string }>(`diff:${root}/${path}`, () => api("/api/run/diff", { root, path }));
  const feed = useEvents<StudioEvent>(root, path, false);
  if (!root || !path) return <Empty>Pick a run on the Runs screen.</Empty>;
  return (
    <div className={`screen before-after ${present ? "present-screen" : ""}`}>
      {!present && (
        <header className="screen-head">
          <h2>Before / after: {path.split("/").pop()}</h2>
          <a href={runHash({ root, path })}>Replay</a>
          <a href={`${afterHash({ root, path })}&present=1`}>Present</a>
        </header>
      )}
      <Async res={res} what="Loading the run">
        {(d) =>
          d.kind !== "v2" ? (
            <Empty>Before / after is for agent-team cleanups; this is a {d.kind === "v1" ? "v1 sweep" : "watch folder"}.</Empty>
          ) : feed.error ? (
            <ErrorBox error={feed.error} />
          ) : !feed.done || diff.loading ? (
            <Loading what="Loading the recording" />
          ) : present ? (
            <PresentAfter detail={d} events={feed.events} diff={diff.data?.text || ""} />
          ) : (
            <View detail={d} events={feed.events} diff={diff.data?.text || ""} />
          )
        }
      </Async>
    </div>
  );
}
