import type { RunDetail } from "../api";
import { type Decision, type RunState } from "../state/fold";
import { Status, seconds } from "./common";

// A budget gauge turns amber then red as it fills; a progress gauge stays green.
function Gauge({
  label,
  used,
  limit,
  unit = "",
  progress = false,
}: {
  label: string;
  used: number | null;
  limit?: number;
  unit?: string;
  progress?: boolean;
}) {
  const share = limit && used !== null ? Math.min(used / limit, 1) : 0;
  const tone = progress ? "good" : share > 0.9 ? "bad" : share > 0.7 ? "warn" : "good";
  return (
    <div className="gauge" title={limit ? `${label}: ${used ?? "-"} of ${limit}${unit}` : label}>
      <div className="gauge-top">
        <span className="gauge-value">
          {used ?? "-"}
          {used !== null && unit}
        </span>
        {limit ? <span className="muted small"> / {limit}{unit}</span> : null}
      </div>
      {limit ? (
        <div className="bar" role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used ?? 0} aria-label={label}>
          <div className={`fill tone-${tone}`} style={{ width: `${share * 100}%` }} />
        </div>
      ) : (
        <div className="bar empty" />
      )}
      <div className="gauge-label">{label}</div>
    </div>
  );
}

export function MetricsBar({ state, detail }: { state: RunState; detail: RunDetail | null }) {
  const stats = detail?.report?.stats || {};
  const done = Object.values(state.packages).filter((p) => ["kept", "rolled_back", "repaired", "skipped"].includes(p.status));
  const kept = done.filter((p) => p.status === "kept" || p.status === "repaired").length;
  const slop = state.candidates ? state.applied / state.candidates : 0;
  const tokens = state.finished && stats.prompt_tokens !== undefined ? stats.prompt_tokens + stats.completion_tokens : null;
  const minutes = state.budget.minutes;
  return (
    <div className="metrics" aria-label="Run metrics">
      <div className="slop-meter" title="edits applied out of the candidates found">
        <div className="gauge-label">Slop meter</div>
        <div className="bar big">
          <div className="fill tone-good" style={{ width: `${slop * 100}%` }} />
        </div>
        <div className="small">
          {state.applied} cleaned of {state.candidates} found
        </div>
      </div>
      <Gauge label="packages done" used={done.length} limit={state.packageOrder.length || undefined} progress />
      <div className="gauge">
        <div className="gauge-top">
          <span className="gauge-value">{kept}</span>
          <span className="muted small"> kept, {done.length - kept} not</span>
        </div>
        <div className="gauge-label">package outcomes</div>
      </div>
      <Gauge label="test runs" used={state.testRuns} limit={state.budget.test_runs} />
      <Gauge label="probe cases" used={state.probes} />
      <Gauge label="probe coverage" used={state.coverage === null ? null : Math.round(state.coverage * 100)} unit="%" />
      <Gauge label="LLM calls" used={state.llmCalls} limit={state.budget.llm_calls} />
      <div className="gauge">
        <div className="gauge-top">
          <span className="gauge-value">{tokens === null ? "-" : tokens.toLocaleString()}</span>
        </div>
        <div className="gauge-label">tokens{tokens === null && !state.finished ? " (at the end)" : ""}</div>
      </div>
      <Gauge label="elapsed (min)" used={Math.round((state.t / 60) * 10) / 10} limit={minutes} />
      <div className="gauge verdict">
        <div className="gauge-top">{state.finished ? <Status value={state.verdict} /> : <Status value="in progress" />}</div>
        <div className="gauge-label">{state.phase || "starting"}</div>
      </div>
    </div>
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
          <span className="rule">{d.rule.replace(/_/g, " ")}</span>
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
