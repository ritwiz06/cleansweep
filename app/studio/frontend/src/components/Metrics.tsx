import type { RunDetail } from "../api";
import { type Decision, type RunState } from "../state/fold";
import { formatNumber, ruleLabel } from "../state/labels";
import { Status, StatsRow, seconds } from "./common";

const DONE = ["kept", "rolled_back", "repaired", "reverted", "skipped"];

// The rest of a run's numbers, for the Report tab: the work packages, the budgets (used of the
// limit), the probes and the tokens.
export function RunNumbers({ state, detail }: { state: RunState; detail: RunDetail | null }) {
  const stats = detail?.report?.stats || {};
  const tokens = state.finished && stats.prompt_tokens !== undefined ? stats.prompt_tokens + stats.completion_tokens : null;
  // the events miss runs a step makes without a message; a finished run has the exact count
  const testRuns = typeof stats.test_runs === "number" ? stats.test_runs : state.testRuns;
  const done = Object.values(state.packages).filter((p) => DONE.includes(p.status)).length;
  const minutes = Math.round((state.t / 60) * 10) / 10;
  const of = (used: number, limit?: number) => (limit ? `${formatNumber(used)} / ${formatNumber(limit)}` : formatNumber(used));
  const share = (used: number, limit?: number) => (limit ? used / limit : undefined);
  return (
    <StatsRow
      label="Run numbers"
      items={[
        { label: "Work packages done", value: of(done, state.packageOrder.length || undefined) },
        { label: "Test runs used", value: of(testRuns, state.budget.test_runs), share: share(testRuns, state.budget.test_runs) },
        { label: "LLM calls used", value: of(state.llmCalls, state.budget.llm_calls), share: share(state.llmCalls, state.budget.llm_calls) },
        { label: "Minutes used", value: of(minutes, state.budget.minutes), share: share(minutes, state.budget.minutes) },
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
