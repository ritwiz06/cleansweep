// The phase timeline's geometry: every phase gets a minimum width so its name and time stay
// readable ("AUDIT 1.3 s"), the current one the width of its full name, and the rest of the bar
// is shared by duration.

export const MIN_PHASE = 72;
export const GAP = 2;

// The width a phase's label needs: its name in 12px bold capitals and the padding.
export function labelWidth(name: string): number {
  return Math.round(name.length * 8.2 + 18);
}

export function phaseWidths(durations: number[], width: number, mins: number[]): number[] {
  const n = durations.length;
  if (!n) return [];
  const free = Math.max(width - GAP * (n - 1), 0);
  const floor = mins.reduce((a, b) => a + b, 0);
  if (floor >= free) return mins.map((m) => (m * free) / floor);
  const total = durations.reduce((a, b) => a + b, 0);
  return durations.map((d, i) => mins[i] + (free - floor) * (total > 0 ? d / total : 1 / n));
}

// Where a moment falls on the bar, in pixels: inside its phase, by its share of that phase.
export function positionOf(t: number, spans: { start: number; dur: number }[], widths: number[]): number {
  let left = 0;
  for (let i = 0; i < spans.length; i++) {
    const s = spans[i];
    if (t <= s.start + s.dur || i === spans.length - 1) {
      const frac = s.dur > 0 ? Math.min(Math.max((t - s.start) / s.dur, 0), 1) : 0.5;
      return left + widths[i] * frac;
    }
    left += widths[i] + GAP;
  }
  return left;
}
