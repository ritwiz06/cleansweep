import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { type Decision, type RunState } from "../state/fold";
import { MIN_PHASE, labelWidth, phaseWidths, positionOf, timeAt } from "../state/timeline";
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

// Moving through a replay on the timeline itself: a click or a drag goes to that moment; the
// arrow keys move one event, Page Up / Page Down ten, Home and End to either end.
export interface Seek {
  clock: number;
  count: number;
  total: number;
  toTime: (t: number) => void;
  toCount: (n: number) => void;
}

const KEYS: Record<string, (count: number, total: number) => number> = {
  ArrowRight: (c) => c + 1,
  ArrowLeft: (c) => c - 1,
  PageDown: (c) => c + 10,
  PageUp: (c) => c - 10,
  Home: () => 0,
  End: (_, total) => total,
};

export function PhaseTimeline({ state, onDecision, seek }: { state: RunState; onDecision?: (d: Decision) => void; seek?: Seek }) {
  const { ref, width } = useWidth();
  const dragging = useRef(false);
  const spans = state.phases.map((p) => ({ ...p, dur: Math.max((p.end ?? state.t) - p.start, 0) }));
  const current = state.finished ? -1 : spans.length - 1;
  // every name in full when the bar has room for them all; the current one always
  const mins = spans.map((s) => Math.max(MIN_PHASE, labelWidth(phaseName(s.phase))));
  const widths = phaseWidths(
    spans.map((s) => s.dur),
    width,
    mins,
  );
  const seekAt = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    seek?.toTime(timeAt(e.clientX - box.left, spans, widths));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const move = KEYS[e.key];
    if (!seek || !move) return;
    seek.toCount(Math.max(0, Math.min(seek.total, move(seek.count, seek.total))));
    e.preventDefault();
  };
  const slider = seek
    ? {
        role: "slider",
        tabIndex: 0,
        "aria-label": "Scrubber",
        "aria-valuemin": 0,
        "aria-valuemax": seek.total,
        "aria-valuenow": seek.count,
        "aria-valuetext": `event ${seek.count} of ${seek.total}, ${seconds(seek.clock)}`,
        onKeyDown: onKey,
        onPointerDown: (e: PointerEvent<HTMLDivElement>) => {
          dragging.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          seekAt(e);
        },
        onPointerMove: (e: PointerEvent<HTMLDivElement>) => dragging.current && seekAt(e),
        onPointerUp: () => (dragging.current = false),
      }
    : {};
  return (
    <div className="timeline" aria-label="Phase timeline">
      <div className={seek ? "timeline-bar scrub" : "timeline-bar"} ref={ref} {...slider}>
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
        {seek && spans.length > 0 && <div className="playhead" style={{ left: positionOf(seek.clock, spans, widths) }} aria-hidden />}
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
    </div>
  );
}
