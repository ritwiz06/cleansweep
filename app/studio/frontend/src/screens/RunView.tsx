import { useEffect, useMemo, useState } from "react";
import { afterHash, api, runHash, useApi, type RunDetail } from "../api";
import { AgentGraph } from "../components/AgentGraph";
import { RunContext } from "../components/Artifact";
import { DiffView } from "../components/Code";
import { Async, Card, Empty, ErrorBox, Loading, PageHeader, Tabs } from "../components/common";
import { ItemBoard } from "../components/ItemBoard";
import { MessageBoard } from "../components/MessageBoard";
import { Decisions, MetricsBar } from "../components/Metrics";
import { DocFile, Packages } from "../components/Packages";
import { PhaseTimeline } from "../components/PhaseTimeline";
import { ProjectView, useProjectFiles } from "../components/ProjectView";
import { Tour, type TourStep } from "../components/Tour";
import { Transport } from "../components/Transport";
import type { Decision, StudioEvent } from "../state/fold";
import { useEvents, useFolded, usePlayer } from "../state/hooks";
import { KIND_LABEL } from "./Runs";
import { V1Run } from "./V1Run";

type Tab = "project" | "overview" | "messages" | "items" | "packages" | "report";
const TOUR_AT = 0.6;

function ReportTab({ detail }: { detail: RunDetail }) {
  const docs = detail.docs.filter((d) => d.endsWith(".md"));
  const [doc, setDoc] = useState(docs.includes("CLEANUP_REPORT.md") ? "CLEANUP_REPORT.md" : docs[0]);
  const diff = useApi<{ text: string }>(`diff:${detail.root}/${detail.path}`, () =>
    api("/api/run/diff", { root: detail.root, path: detail.path }),
  );
  return (
    <div className="grid two">
      <Card title="Documents">
        {docs.length ? (
          <>
            <Tabs tabs={docs.map((d) => ({ key: d, label: d }))} value={doc} onChange={setDoc} />
            <DocFile root={detail.root} path={detail.path} name={doc} />
          </>
        ) : (
          <Empty>The Reporter writes CLEANUP_REPORT.md at the end of the run.</Empty>
        )}
      </Card>
      <Card title="Whole diff">
        <Async res={diff} what="Loading the diff" empty={(d) => (d.text ? null : "No diff (yet).")}>
          {(d) => <DiffView text={d.text} maxHeight={640} />}
        </Async>
      </Card>
    </div>
  );
}

// The tour of a replay: the controls, the numbers, the phases, the project, the agents, what next.
function tourSteps(setTab: (t: Tab) => void, show: () => void): TourStep[] {
  return [
    {
      target: ".transport",
      title: "Play the recording",
      text: "Play, step, or jump to the Manager's next decision. The scrubber moves through the whole run.",
      enter: () => {
        setTab("project");
        show();
      },
    },
    { target: ".metrics", title: "The numbers so far", text: "How much slop is cleaned, and how much of each budget (test runs, LLM calls, time) the run has used." },
    { target: ".timeline", title: "The phases", text: "The run's phases from left to right. Each mark below is a decision of the Manager; click one to jump there." },
    {
      target: ".project",
      title: "The project",
      text: "Every file, class and function a detector flagged, in its state's color, glyph and name. Click one for its evidence and diff.",
      enter: () => setTab("project"),
    },
    {
      target: ".agent-graph",
      title: "The agent team",
      text: "The Manager between the research and development squads. Messages travel from sender to recipient; the highlighted agent is at work.",
      enter: () => setTab("overview"),
    },
    { target: ".page-actions", title: "What next", text: "Before / after shows the finished cleanup, change by change. Present shows the run on a projector." },
  ];
}

function V2Run({ detail, live, reload, tour }: { detail: RunDetail; live: boolean; reload: () => void; tour: boolean }) {
  const feed = useEvents<StudioEvent>(detail.root, detail.path, live);
  const player = usePlayer(feed.events);
  const count = live ? feed.events.length : player.count;
  const state = useFolded(feed.events, count);
  const files = useProjectFiles(detail.root, detail.path);
  const [tab, setTab] = useState<Tab>("project");
  // the tour shows the run part-way, with candidates in every state
  const steps = useMemo(() => tourSteps(setTab, () => player.setCount(Math.round(feed.events.length * TOUR_AT))), [feed.events]);
  // a live run writes its file list and report as it goes: read them again once events arrive
  // and when it ends
  const started = feed.events.length > 0;
  useEffect(() => {
    if (!live || !started) return;
    reload();
    files.reload();
  }, [live, started, feed.done]);
  const end = feed.events.length ? feed.events[feed.events.length - 1].t : 0;
  const pick = (d: Decision) => {
    if (!live) player.setCount(feed.events.findIndex((e) => e.id === d.eventId) + 1);
  };
  if (feed.error) return <ErrorBox error={feed.error} />;
  if (!live && !feed.done) return <Loading what="Loading the recording" />;
  return (
    <RunContext.Provider value={{ root: detail.root, path: detail.path }}>
      {tour && feed.events.length > 0 && <Tour steps={steps} onClose={() => window.location.replace(runHash(detail))} />}
      {!live && <Transport player={player} total={feed.events.length} end={end} />}
      {live && (
        <div className="live-banner" role="status">
          {feed.done ? "Run finished." : <><span className="spinner small" /> Live: {feed.events.length} events so far</>}
        </div>
      )}
      <MetricsBar state={state} detail={feed.done && state.finished ? detail : null} />
      <PhaseTimeline state={state} onDecision={pick} />
      <Tabs
        tabs={[
          { key: "project", label: "Project" },
          { key: "overview", label: "Agents" },
          { key: "messages", label: `Message board (${state.messages.length})` },
          { key: "items", label: `Items (${state.itemOrder.length})` },
          { key: "packages", label: `Work packages (${state.packageOrder.length})` },
          { key: "report", label: "Report" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "project" && <ProjectView state={state} events={feed.events} detail={detail} files={files.data} />}
      {tab === "overview" && (
        <>
          <Card title="Agent team" className="graph-card">
            <AgentGraph state={state} />
          </Card>
          <div className="grid two side">
            <Card title="The Manager's decisions" scroll>
              <Decisions state={state} onPick={pick} />
            </Card>
            <Card title="Latest thoughts" scroll>
              {state.thoughts.length ? (
                <ul className="thoughts">
                  {state.thoughts.slice(-4).reverse().map((t, i) => (
                    <li key={i}>
                      <b>{t.agent}</b>: {t.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No thoughts yet. Agents record thoughts in their tool loops; runs without an LLM record none.</p>
              )}
              {state.budgetNotes.map((b, i) => (
                <p key={i} className="small warn-text">
                  budget: {b.agent} {b.text}
                </p>
              ))}
              {state.errors.map((e, i) => (
                <p key={i} className="small bad-text">
                  error in {e.agent}: {e.text}
                </p>
              ))}
            </Card>
          </div>
        </>
      )}
      {tab === "messages" && <MessageBoard state={state} />}
      {tab === "items" && <ItemBoard state={state} />}
      {tab === "packages" && <Packages state={state} detail={detail} />}
      {tab === "report" && <ReportTab detail={detail} />}
    </RunContext.Provider>
  );
}

const HELP_LIVE = "A cleanup as it happens: the agents' phases, messages and edits, and every candidate's state in the project's files.";
const HELP_REPLAY = "A recorded cleanup, played back: the agents' phases, messages and edits, and every candidate's state in the project's files.";

function meta(d: RunDetail): string {
  const model = d.model || (d.report?.stats?.llm_calls ? "not recorded" : d.finished ? "none" : "-");
  return [KIND_LABEL[d.kind] || d.kind, d.target, d.mode && `${d.mode} mode`, `model ${model}`].filter(Boolean).join(" · ");
}

export function RunView({ root, path, live, tour = false }: { root: string; path: string; live: boolean; tour?: boolean }) {
  const res = useApi<RunDetail>(`${root}/${path}`, () => api("/api/run", { root, path }));
  const [title, setTitle] = useState(path);
  useEffect(() => setTitle(path.split("/").pop() || path), [path]);
  if (!root || !path) return <Empty action={{ label: "Open Runs", href: "#/runs" }}>Pick a run to replay.</Empty>;
  const d = res.data;
  return (
    <div className="screen run-view">
      <PageHeader
        title={`${live ? "Live run" : "Replay"}: ${title}`}
        description={d ? meta(d) : " "}
        help={live ? HELP_LIVE : HELP_REPLAY}
        actions={
          d && (
            <>
              {d.live && !live && (
                <a className="button" href={`#/run?${new URLSearchParams({ root, path })}`}>
                  Follow live
                </a>
              )}
              {d.kind === "v2" && (
                <>
                  <a className="button" href={afterHash({ root, path })}>
                    Before / after
                  </a>
                  <a className="button" href={`#/present?${new URLSearchParams({ root, path, ...(live ? { live: "1" } : {}) })}`}>
                    Present
                  </a>
                </>
              )}
            </>
          )
        }
      />
      <Async res={res} what="Loading the run">
        {(d) =>
          d.kind === "v1" ? (
            <V1Run detail={d} live={live} />
          ) : d.kind === "watch" ? (
            <Empty action={{ label: "Open in Watch", href: `#/watch?${new URLSearchParams({ root, path })}` }}>This is a watch folder.</Empty>
          ) : (
            <V2Run detail={d} live={live} reload={res.reload} tour={tour && !live} />
          )
        }
      </Async>
    </div>
  );
}
