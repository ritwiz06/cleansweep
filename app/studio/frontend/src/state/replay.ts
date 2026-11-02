// Replay clock: which events have happened at a recorded time, and where the next decision is.

export interface Timed {
  t: number;
  kind: string;
  payload?: { rule?: string; back?: boolean };
}

// The number of events at or before `clock` (events are in time order).
export function countAt(events: Timed[], clock: number): number {
  let lo = 0;
  let hi = events.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (events[mid].t <= clock) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function isDecision(e: Timed): boolean {
  if (e.kind === "decision") return Boolean(e.payload?.rule);
  if (e.kind === "phase_change") return Boolean(e.payload?.back);
  return e.kind === "stage_done" || e.kind === "batch_result";
}

// The count that shows the next decision after the first `count` events, or the end.
export function nextDecision(events: Timed[], count: number): number {
  for (let i = count; i < events.length; i++) if (isDecision(events[i])) return i + 1;
  return events.length;
}

export function clockOf(events: Timed[], count: number): number {
  return count > 0 ? events[Math.min(count, events.length) - 1].t : 0;
}
