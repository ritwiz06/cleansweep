import { useLayoutEffect, useRef, useState } from "react";
import { PHASES, type Decision, type RunState } from "../state/fold";
import { MIN_PHASE, labelWidth, phaseWidths, positionOf } from "../state/timeline";
import { seconds } from "./common";

const phaseName = (phase: string) => phase.replace("_", " ");

// The bar's width in pixels, measured before the first paint and kept up to date as the screen
// changes size.
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export function PhaseTimeline({ state, onDecision }: { state: RunState; onDecision?: (d: Decision) => void }) {
  const { ref, width } = useWidth();
  const spans = state.phases.map((p) => ({ ...p, dur: Math.max((p.end ?? state.t) - p.start, 0) }));
  const current = state.finished ? -1 : spans.length - 1;
  // every name in full when the bar has room for them all; the current one always
  const mins = spans.map((s) => Math.max(MIN_PHASE, labelWidth(phaseName(s.phase))));
  const widths = phaseWidths(
    spans.map((s) => s.dur),
    width,
    mins,
  );
  const now = state.phase && !state.finished ? PHASES.indexOf(state.phase as (typeof PHASES)[number]) : -1;
  const next = now >= 0 ? PHASES.slice(now + 1).find((p) => p !== "DONE") : undefined;
  return (
    <div className="timeline" aria-label="Phase timeline">
      <div className="timeline-bar" ref={ref}>
        {spans.length === 0 && <div className="muted small">Waiting for the first phase...</div>}
        {spans.map((s, i) => (
          <div
            key={`${s.phase}-${i}`}
            className={`span phase-${s.phase.toLowerCase()} ${i === current ? "current" : ""} ${s.back ? "back" : ""}`}
            style={{ width: widths[i] }}
            title={`${phaseName(s.phase)}: ${seconds(s.dur)}${s.back ? " (step back)" : ""}\n${s.reason}`}
          >
            <span className="span-label">
              {s.back && "↩ "}
              {phaseName(s.phase)}
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
            style={{ left: positionOf(d.t, spans, widths) }}
            title={`${d.rule}: ${d.text}`}
            aria-label={`decision: ${d.text}`}
            onClick={() => onDecision?.(d)}
          />
        ))}
      </div>
      {(next || state.backSteps > 0) && (
        <div className="phase-legend">
          {next && <span className="legend-item pending">next: {phaseName(next)}</span>}
          {state.backSteps > 0 && <span className="legend-item back">↩ {state.backSteps} step back{state.backSteps > 1 ? "s" : ""}</span>}
        </div>
      )}
    </div>
  );
}
