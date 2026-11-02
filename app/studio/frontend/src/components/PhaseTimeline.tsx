import { PHASES, phaseSeconds, type Decision, type RunState } from "../state/fold";
import { seconds } from "./common";

const MIN_SHARE = 0.04;

// Each phase span gets a width by its time (with a minimum), and a time maps onto that scale.
function scale(state: RunState) {
  const spans = state.phases.map((p) => ({ ...p, dur: Math.max((p.end ?? state.t) - p.start, 0) }));
  const total = spans.reduce((a, s) => a + s.dur, 0) || 1;
  const weights = spans.map((s) => Math.max(s.dur, total * MIN_SHARE));
  const sum = weights.reduce((a, w) => a + w, 0) || 1;
  const at = (t: number) => {
    let x = 0;
    for (let i = 0; i < spans.length; i++) {
      const s = spans[i];
      const end = s.start + s.dur;
      if (t <= end || i === spans.length - 1) {
        const frac = s.dur > 0 ? Math.min(Math.max((t - s.start) / s.dur, 0), 1) : 0.5;
        return ((x + weights[i] * frac) / sum) * 100;
      }
      x += weights[i];
    }
    return 100;
  };
  return { spans, weights, sum, at };
}

export function PhaseTimeline({
  state,
  onDecision,
}: {
  state: RunState;
  onDecision?: (d: Decision) => void;
}) {
  const { spans, weights, sum, at } = scale(state);
  const totals = phaseSeconds(state);
  const current = state.finished ? null : spans.length - 1;
  return (
    <div className="timeline" aria-label="Phase timeline">
      <div className="timeline-bar">
        {spans.length === 0 && <div className="muted small">Waiting for the first phase...</div>}
        {spans.map((s, i) => (
          <div
            key={`${s.phase}-${i}`}
            className={`span phase-${s.phase.toLowerCase()} ${i === current ? "current" : ""} ${s.back ? "back" : ""}`}
            style={{ width: `${(weights[i] / sum) * 100}%` }}
            title={`${s.phase}: ${seconds(s.dur)}${s.back ? " (step back)" : ""}\n${s.reason}`}
          >
            <span className="span-label">
              {s.back && "↩ "}
              {s.phase.replace("_", " ")}
            </span>
            <span className="span-time">{seconds(s.dur)}</span>
          </div>
        ))}
      </div>
      <div className="timeline-marks">
        {state.decisions.map((d) => (
          <button
            key={d.eventId}
            className={`mark rule-${d.rule} ${d.status ? `status-${d.status}` : ""}`}
            style={{ left: `${at(d.t)}%` }}
            title={`${d.rule}: ${d.text}`}
            aria-label={`decision: ${d.text}`}
            onClick={() => onDecision?.(d)}
          />
        ))}
      </div>
      <div className="phase-legend">
        {PHASES.filter((p) => p !== "DONE").map((p) => (
          <span key={p} className={`legend-item ${state.phase === p && !state.finished ? "active" : ""} ${totals[p] !== undefined ? "" : "pending"}`}>
            <i className={`dot phase-${p.toLowerCase()}`} />
            {p.replace("_", " ")} <b>{totals[p] !== undefined ? seconds(totals[p]) : "-"}</b>
          </span>
        ))}
        {state.backSteps > 0 && <span className="legend-item back">↩ {state.backSteps} step back{state.backSteps > 1 ? "s" : ""}</span>}
      </div>
    </div>
  );
}
