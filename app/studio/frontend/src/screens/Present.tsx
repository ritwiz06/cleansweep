import { useEffect, useMemo, useState } from "react";
import { api, runHash, useApi, type RunDetail } from "../api";
import { AgentGraph } from "../components/AgentGraph";
import { AgentIcon } from "../components/AgentIcon";
import { Async, Empty, ErrorBox, Loading } from "../components/common";
import { PresentShell } from "../components/PresentShell";
import { TreeList, itemKey, treeFiles, useProjectFiles, useTreeView } from "../components/ProjectView";
import { captionSteps } from "../state/caption";
import { agentName, repoName, type StudioEvent } from "../state/fold";
import { useEvents, useFolded } from "../state/hooks";
import { targetName } from "../state/names";
import { STEP_MS, nextDecisionStep } from "../state/present";
import { buildTree } from "../state/tree";

type View = "project" | "agents";

function viewHash(detail: RunDetail, live: boolean, view: View): string {
  return `#/present?${new URLSearchParams({ root: detail.root, path: detail.path, ...(live ? { live: "1" } : {}), ...(view === "agents" ? { view } : {}) })}`;
}

// Project or Agents: what the big panel shows (G switches).
function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="view-switch" role="group" aria-label="View" title="G switches">
      {(["project", "agents"] as View[]).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={(e) => {
            onChange(v);
            // a focused button would take the next space bar press as a click
            e.currentTarget.blur();
          }}
        >
          {v === "project" ? "Project" : "Agents"}
        </button>
      ))}
    </div>
  );
}

function Run({ detail, events, live, view }: { detail: RunDetail; events: StudioEvent[]; live: boolean; view: View }) {
  const steps = useMemo(() => captionSteps(events), [events]);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const here = live ? steps.length - 1 : Math.min(at, steps.length - 1);
  const step = here >= 0 ? steps[here] : null;
  const count = live ? events.length : step ? step.index + 1 : 0;
  const state = useFolded(events, count);
  const files = useProjectFiles(detail.root, detail.path);
  const list = useMemo(() => treeFiles(files.data, events), [files.data, events.length]);
  const tree = useMemo(() => buildTree(list, state, (state.repo || detail.target || "project").replace(/^local:/, "")), [list, state]);
  const treeView = useTreeView(tree, view === "project", count);
  useEffect(() => {
    if (!playing || live) return;
    const timer = setInterval(() => {
      setAt((a) => {
        if (a >= steps.length - 1) {
          setPlaying(false);
          return a;
        }
        return a + 1;
      });
    }, STEP_MS);
    return () => clearInterval(timer);
  }, [playing, live, steps.length]);
  const go = (k: number) => setAt(Math.max(0, Math.min(steps.length - 1, k)));
  const previous = () => {
    for (let k = here - 1; k >= 0; k--) if (steps[k].decision) return go(k);
    go(0);
  };
  // the one item the latest step is about, when there is one; a step about many has none
  const atWork = state.focus.length === 1 && state.items[state.focus[0]] ? itemKey(state.items[state.focus[0]].unit) : null;
  const exit = runHash(detail, live ? "live" : "replay");
  const setView = (v: View) => (window.location.hash = viewHash(detail, live, v));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "g" && e.key !== "G") return;
      if ((e.target as HTMLElement)?.closest?.("input, select, textarea")) return;
      setView(view === "project" ? "agents" : "project");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  return (
    <PresentShell
      extra={<ViewSwitch view={view} onChange={setView} />}
      title={`${live ? "Live" : "Replay"}: ${targetName(detail.target) || repoName(state.repo || detail.name)}`}
      position={live ? `${steps.length} steps so far` : `step ${here + 1} of ${steps.length}`}
      progress={steps.length ? (here + 1) / steps.length : 0}
      playing={playing}
      onPlay={() => {
        if (here >= steps.length - 1) setAt(0);
        setPlaying(!playing);
      }}
      onNext={() => go(nextDecisionStep(steps, here))}
      onPrev={previous}
      onStep={(d) => go(here + d)}
      exit={exit}
    >
      <div className="caption" aria-live="polite" aria-label="Caption">
        {step ? (
          <>
            <AgentIcon agent={step.agent} />
            <p>
              <b>{agentName(step.agent)}</b> {step.text}
            </p>
          </>
        ) : (
          <p className="muted">Waiting for the first step...</p>
        )}
      </div>
      {/* the reason, when the step has one */}
      {step?.detail && <p className="caption-detail">{step.detail}</p>}
      <div className={`present-run view-${view}`}>
        {view === "agents" ? (
          <div className="present-graph">
            <AgentGraph state={state} />
          </div>
        ) : (
          <div className="present-tree">
            <TreeList view={treeView} chosen={null} onSelect={() => undefined} atWork={atWork} />
          </div>
        )}
      </div>
    </PresentShell>
  );
}

export function Present({ root, path, live, view = "project" }: { root: string; path: string; live: boolean; view?: View }) {
  const res = useApi<RunDetail>(`${root}/${path}`, () => api("/api/run", { root, path }));
  const feed = useEvents<StudioEvent>(root, path, live);
  if (!root || !path) return <Empty action={{ label: "Open Runs", href: "#/runs" }}>Pick a run to present.</Empty>;
  return (
    <div className="screen present-screen">
      <Async res={res} what="Loading the run">
        {(d) =>
          d.kind !== "v2" ? (
            <Empty action={{ label: "Open the replay", href: runHash({ root, path }) }}>Presentation mode is for agent-team cleanups.</Empty>
          ) : feed.error ? (
            <ErrorBox error={feed.error} />
          ) : !live && !feed.done ? (
            <Loading what="Loading the recording" />
          ) : (
            <Run detail={d} events={feed.events} live={live} view={view} />
          )
        }
      </Async>
    </div>
  );
}
