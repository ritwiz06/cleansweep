import { useEffect, useMemo, useState } from "react";
import { api, runHash, useApi, type RunDetail } from "../api";
import { Pointer } from "../components/AfterParts";
import { Decisions } from "../components/Metrics";
import { AgentGraph } from "../components/AgentGraph";
import { AgentIcon } from "../components/AgentIcon";
import { Async, Empty, ErrorBox, Loading } from "../components/common";
import { PresentShell } from "../components/PresentShell";
import { TreeList, itemKey, treeFiles, useProjectFiles, useTreeView } from "../components/ProjectView";
import { StateLegend } from "../components/states";
import { captionSteps, type CaptionStep } from "../state/caption";
import { PHASES, SQUADS, agentName, repoName, roleOf, type RunState, type StudioEvent } from "../state/fold";
import { useEvents, useFolded } from "../state/hooks";
import { STEP_MS, nextDecisionStep } from "../state/present";
import { buildTree } from "../state/tree";

const ROLE: Record<string, string> = {
  manager: "runs the phases, hands out the work and keeps the budget",
  explorer: "reads the project and writes the brief",
  auditor: "runs the detectors and lists the candidates",
  investigator: "gathers evidence on one candidate and decides",
  planner: "groups the safe candidates into work packages",
  engineer: "applies a package's edits and commits them",
  tester: "runs the project's tests",
  validator: "probes behavior before and after, checks public names",
  fixer: "repairs a failed package or rolls it back",
  reporter: "writes the report and the pull request text",
  solo: "does every job alone (an ablation)",
};

function Counter({ label, value, state }: { label: string; value: number | string; state?: string }) {
  return (
    <div className={`counter ${state ? `st-${state}` : ""}`}>
      <div className="counter-value">{value}</div>
      <div className="counter-label">{label}</div>
    </div>
  );
}

function Spotlight({ step, state }: { step: CaptionStep | null; state: RunState }) {
  const agent = step?.agent || "manager";
  const role = roleOf(agent);
  const stages = Object.values(state.items).map((i) => i.stage);
  const count = (...s: string[]) => stages.filter((x) => s.includes(x)).length;
  const done = Object.values(state.packages).filter((p) => ["kept", "repaired", "rolled_back", "reverted", "skipped"].includes(p.status)).length;
  return (
    <aside className="spotlight" aria-label="Active agent">
      <div className={`spot-agent squad-${SQUADS[role] === "single" ? "manager" : SQUADS[role] || "manager"}`}>
        <AgentIcon agent={agent} />
        <div>
          <div className="spot-name">{agentName(agent)}</div>
          <div className="spot-role">{ROLE[role] || ""}</div>
        </div>
      </div>
      <ol className="phase-steps" aria-label="Phases">
        {PHASES.filter((p) => p !== "DONE").map((p) => {
          const seen = state.phases.some((s) => s.phase === p);
          const now = state.phase === p && !state.finished;
          return (
            <li key={p} className={now ? "now" : seen ? "seen" : ""} aria-current={now ? "step" : undefined}>
              {p.replace("_", " ").toLowerCase()}
            </li>
          );
        })}
      </ol>
      <div className="counters">
        <Counter label="candidates" value={state.itemOrder.length} />
        <Counter label="investigating" value={count("investigating")} state="investigating" />
        <Counter label="suggestions" value={count("suggest")} state="suggest" />
        <Counter label="kept" value={count("kept", "repaired")} state="kept" />
        <Counter label="rolled back" value={count("rolled_back")} state="rolled_back" />
        <Counter label="packages done" value={`${done}/${state.packageOrder.length}`} />
      </div>
      {state.focus.length === 1 && state.items[state.focus[0]] ? (
        <section className="spot-item" aria-label="The item at work">
          <h3>
            At work on <code>{state.items[state.focus[0]].unit.split("::").pop()}</code>
          </h3>
          <Pointer note={{ items: [state.focus[0]], match: "exact" }} state={state} />
        </section>
      ) : (
        state.decisions.length > 0 && (
          <section className="spot-item" aria-label="The Manager's latest decisions">
            <h3>The Manager's latest decisions</h3>
            <Decisions state={{ ...state, decisions: state.decisions.slice(-3) }} />
          </section>
        )
      )}
    </aside>
  );
}

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
  const recent = steps.slice(Math.max(0, here - 1), here).reverse();
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
      title={`${live ? "Live" : "Replay"}: ${repoName(state.repo || detail.target || detail.name)}`}
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
      {/* without the side panel (the agent graph on a smaller screen) the agent's role joins the caption */}
      {view === "agents" && step && (
        <p className="caption-role">
          {agentName(step.agent)} {ROLE[roleOf(step.agent)] || ""}
        </p>
      )}
      {/* always two lines high, so the panel below keeps its size from step to step */}
      <p className="caption-detail">{step?.detail || ""}</p>
      {recent[0] && (
        <p className="caption-before" aria-label="The step before">
          Before that: {agentName(recent[0].agent)} {recent[0].text}
        </p>
      )}
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
        <Spotlight step={step} state={state} />
      </div>
      {view === "project" && (
        <div className="present-foot">
          <StateLegend />
        </div>
      )}
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
