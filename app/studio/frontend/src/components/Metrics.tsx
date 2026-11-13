import type { RunDetail } from "../api";
import { type Decision, type RunState } from "../state/fold";
import { formatNumber, ruleLabel } from "../state/labels";
import { Status, StatsRow, seconds } from "./common";

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
