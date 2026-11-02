import { useEffect, useState } from "react";
import { api, useApi, type RunDetail } from "../api";
import { AgentGraph } from "../components/AgentGraph";
import { RunContext } from "../components/Artifact";
import { DiffView } from "../components/Code";
import { Async, Card, Empty, ErrorBox, Loading, Tabs } from "../components/common";
import { ItemBoard } from "../components/ItemBoard";
import { MessageBoard } from "../components/MessageBoard";
import { Decisions, MetricsBar } from "../components/Metrics";
import { DocFile, Packages } from "../components/Packages";
import { PhaseTimeline } from "../components/PhaseTimeline";
import { Transport } from "../components/Transport";
import type { Decision, StudioEvent } from "../state/fold";
import { useEvents, useFolded, usePlayer } from "../state/hooks";
import { V1Run } from "./V1Run";

type Tab = "overview" | "messages" | "items" | "packages" | "report";

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

function V2Run({ detail, live }: { detail: RunDetail; live: boolean }) {
  const feed = useEvents<StudioEvent>(detail.root, detail.path, live);
  const player = usePlayer(feed.events);
  const count = live ? feed.events.length : player.count;
  const state = useFolded(feed.events, count);
  const [tab, setTab] = useState<Tab>("overview");
  const end = feed.events.length ? feed.events[feed.events.length - 1].t : 0;
  const pick = (d: Decision) => {
    if (!live) player.setCount(feed.events.findIndex((e) => e.id === d.eventId) + 1);
  };
  if (feed.error) return <ErrorBox error={feed.error} />;
  if (!live && !feed.done) return <Loading what="Loading the recording" />;
  return (
    <RunContext.Provider value={{ root: detail.root, path: detail.path }}>
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
          { key: "overview", label: "Agents" },
          { key: "messages", label: `Message board (${state.messages.length})` },
          { key: "items", label: `Items (${state.itemOrder.length})` },
          { key: "packages", label: `Work packages (${state.packageOrder.length})` },
          { key: "report", label: "Report" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "overview" && (
        <div className="grid overview">
          <Card title="Agent team">
            <AgentGraph state={state} />
          </Card>
          <div className="side">
            <Card title="The Manager's decisions">
              <Decisions state={state} onPick={pick} />
            </Card>
            <Card title="Latest thoughts">
              {state.thoughts.length ? (
                <ul className="thoughts">
                  {state.thoughts.slice(-4).reverse().map((t, i) => (
                    <li key={i}>
                      <b>{t.agent}</b>: {t.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No thoughts yet; offline runs (--no-llm) decide by rules and record none.</p>
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
        </div>
      )}
      {tab === "messages" && <MessageBoard state={state} />}
      {tab === "items" && <ItemBoard state={state} />}
      {tab === "packages" && <Packages state={state} detail={detail} />}
      {tab === "report" && <ReportTab detail={detail} />}
    </RunContext.Provider>
  );
}

export function RunView({ root, path, live }: { root: string; path: string; live: boolean }) {
  const res = useApi<RunDetail>(`${root}/${path}`, () => api("/api/run", { root, path }));
  const [title, setTitle] = useState(path);
  useEffect(() => setTitle(path.split("/").pop() || path), [path]);
  if (!root || !path) return <Empty>Pick a run on the Runs screen.</Empty>;
  return (
    <div className="screen run-view">
      <header className="screen-head">
        <h2>
          {live ? "Live run" : "Replay"}: {title}
        </h2>
        <Async res={res}>
          {(d) => (
            <span className="muted">
              {d.kind} · {d.target || "?"} · {d.mode || ""} · model {d.model || "none"}
              {d.live && !live && (
                <a className="link" href={`#/run?${new URLSearchParams({ root, path })}`}>
                  {" "}
                  follow live
                </a>
              )}
            </span>
          )}
        </Async>
      </header>
      <Async res={res} what="Loading the run">
        {(d) => (d.kind === "v1" ? <V1Run detail={d} live={live} /> : d.kind === "watch" ? (
          <Empty>
            This is a watch folder. <a href={`#/watch?${new URLSearchParams({ root, path })}`}>Open it on the Watch screen.</a>
          </Empty>
        ) : (
          <V2Run detail={d} live={live} />
        ))}
      </Async>
    </div>
  );
}
