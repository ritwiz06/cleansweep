import { useEffect, useMemo, useState } from "react";
import { api, runHash, useApi, type RunDetail } from "../api";
import { AgentIcon } from "../components/AgentIcon";
import { Async, Empty, ErrorBox, Loading } from "../components/common";
import { PresentShell } from "../components/PresentShell";
import { TreeList, treeFiles, useProjectFiles, useTreeView } from "../components/ProjectView";
import { StateLegend } from "../components/states";
import { captionSteps, type CaptionStep } from "../state/caption";
import { PHASES, SQUADS, agentName, roleOf, type RunState, type StudioEvent } from "../state/fold";
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
    </aside>
  );
}

function Run({ detail, events, live }: { detail: RunDetail; events: StudioEvent[]; live: boolean }) {
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
  const view = useTreeView(tree, true, count);
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
  const recent = steps.slice(Math.max(0, here - 2), here).reverse();
  const exit = runHash(detail, live ? "live" : "replay");
  return (
    <PresentShell
      title={`${live ? "Live" : "Replay"}: ${(state.repo || detail.target || detail.name).replace(/^local:/, "")}`}
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
      <p className="caption-detail">{step?.detail || " "}</p>
      <div className="present-run">
        <div className="present-tree">
          <TreeList view={view} chosen={null} onSelect={() => undefined} />
        </div>
        <Spotlight step={step} state={state} />
      </div>
      <div className="present-foot">
        <StateLegend />
        <ol className="trail" aria-label="Previous steps">
          {recent.map((s) => (
            <li key={s.index}>
              {agentName(s.agent)} {s.text}
            </li>
          ))}
        </ol>
      </div>
    </PresentShell>
  );
}

export function Present({ root, path, live }: { root: string; path: string; live: boolean }) {
  const res = useApi<RunDetail>(`${root}/${path}`, () => api("/api/run", { root, path }));
  const feed = useEvents<StudioEvent>(root, path, live);
  if (!root || !path) return <Empty>Pick a run on the Runs screen.</Empty>;
  return (
    <div className="screen present-screen">
      <Async res={res} what="Loading the run">
        {(d) =>
          d.kind !== "v2" ? (
            <Empty>Presentation mode is for agent-team cleanups.</Empty>
          ) : feed.error ? (
            <ErrorBox error={feed.error} />
          ) : !live && !feed.done ? (
            <Loading what="Loading the recording" />
          ) : (
            <Run detail={d} events={feed.events} live={live} />
          )
        }
      </Async>
    </div>
  );
}
