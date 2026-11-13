import type { RunDetail } from "../api";
import { type Decision, type RunState } from "../state/fold";
import { formatNumber, ruleLabel } from "../state/labels";
import { Status, StatsRow, seconds, type StatItem } from "./common";

// A budget turns amber then red as it fills; progress stays green.
function budget(used: number, limit: number | undefined): Pick<StatItem, "share" | "tone"> {
  if (!limit) return {};
  const share = Math.min(used / limit, 1);
  return { share, tone: share > 0.9 ? "bad" : share > 0.7 ? "warn" : "good" };
}

function outOf(used: number | string, limit?: number) {
  return limit ? (
    <>
      {used}
      <span className="stat-of"> / {limit}</span>
    </>
  ) : (
    used
  );
}

function testRunsOf(state: RunState, detail: RunDetail | null): number {
  const stats = detail?.report?.stats || {};
  // the events miss runs a step makes without a message; a finished run has the exact count
  return typeof stats.test_runs === "number" ? stats.test_runs : state.testRuns;
}

// The run at a glance: the slop cleaned leads, then the packages and the budgets.
export function MetricsBar({ state, detail }: { state: RunState; detail: RunDetail | null }) {
  const done = Object.values(state.packages).filter((p) => ["kept", "rolled_back", "repaired", "reverted", "skipped"].includes(p.status));
  const kept = done.filter((p) => p.status === "kept" || p.status === "repaired").length;
  const testRuns = testRunsOf(state, detail);
  const minutes = Math.round((state.t / 60) * 10) / 10;
  const status = (
    <span className="stat-status">
      {state.finished ? <Status value={state.verdict} /> : <Status value="in progress" />}
      <span className="muted small">{(state.phase || "starting").replace("_", " ")}</span>
    </span>
  );
  return (
    <StatsRow
      label="Run metrics"
      items={[
        {
          label: "Slop cleaned",
          hint: "edits applied of the candidates found",
          value: outOf(state.applied, state.candidates || undefined),
          lead: true,
          share: state.candidates ? state.applied / state.candidates : 0,
          aside: status,
        },
        { label: "Packages done", value: outOf(done.length, state.packageOrder.length || undefined), share: state.packageOrder.length ? done.length / state.packageOrder.length : undefined },
        { label: "Kept / not kept", value: `${kept} / ${done.length - kept}`, hint: "not kept: rolled back, reverted or not applied" },
        { label: "Test runs", value: outOf(testRuns, state.budget.test_runs), ...budget(testRuns, state.budget.test_runs) },
        { label: "LLM calls", value: outOf(state.llmCalls, state.budget.llm_calls), ...budget(state.llmCalls, state.budget.llm_calls) },
        { label: "Elapsed (min)", value: outOf(minutes, state.budget.minutes), ...budget(minutes, state.budget.minutes) },
      ]}
    />
  );
}

// The numbers that matter once a run is over, for the Report tab.
export function RunNumbers({ state, detail }: { state: RunState; detail: RunDetail | null }) {
  const stats = detail?.report?.stats || {};
  const tokens = state.finished && stats.prompt_tokens !== undefined ? stats.prompt_tokens + stats.completion_tokens : null;
  return (
    <StatsRow
      label="Probes and tokens"
      items={[
        { label: "Probe cases", value: formatNumber(state.probes) },
        { label: "Probe coverage of the changed lines", value: state.coverage === null ? "-" : `${Math.round(state.coverage * 100)}%` },
        { label: "LLM tokens", value: tokens === null ? "-" : formatNumber(tokens), hint: "counted when the run ends" },
      ]}
    />
  );
}

export function Decisions({ state, onPick }: { state: RunState; onPick?: (d: Decision) => void }) {
  const manager = state.decisions;
  if (!manager.length) return <p className="muted">The Manager has not decided anything yet.</p>;
  return (
    <ol className="decisions" aria-label="Manager decisions">
      {[...manager].reverse().map((d) => (
        <li key={d.eventId} className={`decision rule-${d.rule}`}>
          <button className="link time" onClick={() => onPick?.(d)} title="show this moment">
            {seconds(d.t)}
          </button>
          <span className="rule">{ruleLabel(d.rule)}</span>
          {d.status && <Status value={d.status} />}
          {d.choice && (
            <span className="choice">
              chose <b>{d.choice}</b>
              {d.options && <span className="muted"> of {d.options.join(" / ")}</span>}
              {d.proposed && <span className="muted"> (next: {d.proposed})</span>}
            </span>
          )}
          <span className="reason">{d.text}</span>
        </li>
      ))}
    </ol>
  );
}
