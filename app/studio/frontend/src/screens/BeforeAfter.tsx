import { useEffect, useMemo, useRef, useState } from "react";
import { afterHash, api, runHash, useApi, type RunDetail } from "../api";
import { FileDiff, MetricsCard, SMALL, TreeCard } from "../components/AfterParts";
import { AgentIcon, agentName } from "../components/AgentIcon";
import { Async, Empty, ErrorBox, Loading, PageHeader } from "../components/common";
import { PresentShell } from "../components/PresentShell";
import { useProjectFiles } from "../components/ProjectView";
import { SideBySide } from "../components/SideBySide";
import { StateChip } from "../components/states";
import { categoryLabel, decisionSteps, packageChecks } from "../state/annotate";
import { afterModel } from "../state/beforeAfter";
import { itemLabel } from "../state/caption";
import type { Item, RunState, StudioEvent } from "../state/fold";
import { useEvents } from "../state/hooks";
import { SLIDE_MS, afterSlides, type Slide } from "../state/present";

// Everything both views draw: the folded run, the parsed diff, both trees and the numbers.
function useAfterModel(detail: RunDetail, events: StudioEvent[], diff: string) {
  const files = useProjectFiles(detail.root, detail.path);
  const model = useMemo(() => afterModel(events, diff, files.data, detail), [events, diff, files.data, detail]);
  return { files, ...model };
}

function View({ detail, events, diff }: { detail: RunDetail; events: StudioEvent[]; diff: string }) {
  const model = useAfterModel(detail, events, diff);
  const { files, state, parsed, list, trees, m } = model;
  const [exporting, setExporting] = useState(false);
  const exportReport = async () => {
    setExporting(true);
    const { downloadHtml, exportHtml } = await import("../components/ExportReport");
    const run = { name: detail.name, target: detail.target, mode: detail.mode, model: detail.model, started: events[0]?.ts || null };
    downloadHtml(exportHtml(model, run), `cleansweep-${detail.name}.html`);
    setExporting(false);
  };
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
        <button onClick={exportReport} disabled={exporting || !state.finished} title="one HTML file: before / after, the trees, every diff and the result">
          {exporting ? "Exporting..." : "Export HTML report"}
        </button>
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
  if (!root || !path) return <Empty action={{ label: "Open Runs", href: "#/runs" }}>Pick a finished cleanup to see what it changed.</Empty>;
  return (
    <div className={`screen before-after ${present ? "present-screen" : ""}`}>
      {!present && (
        <PageHeader
          title={`Before / after: ${path.split("/").pop()}`}
          description="What the cleanup changed: both file trees, the numbers before and after, and every change with the decisions behind it."
          help="Click a changed file for its diff. The note above each change names its category, the agents' decisions, the evidence and the checks it passed."
          actions={
            <>
              <a className="button" href={runHash({ root, path })}>
                Replay
              </a>
              <a className="button" href={`${afterHash({ root, path })}&present=1`}>
                Present
              </a>
            </>
          }
        />
      )}
      <Async res={res} what="Loading the run">
        {(d) =>
          d.kind !== "v2" ? (
            <Empty action={{ label: "Open the replay", href: runHash({ root, path }) }}>
              Before / after is for agent-team cleanups; this is a {d.kind === "v1" ? "Phase 1 sweep" : "watch folder"}.
            </Empty>
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
