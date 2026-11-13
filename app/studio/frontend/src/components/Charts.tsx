// Shared chart pieces: the axis and tooltip styles, and the series names written above a chart,
// beside its title, instead of a legend under it.

export const AXIS = { fill: "var(--muted)", fontSize: 12 };
export const TOOLTIP = { background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" };

export interface LabelBox {
  x?: number | string;
  y?: number | string;
  width?: number | string;
  height?: number | string;
  value?: unknown;
}

type Row = Record<string, unknown>;

// For a LabelList whose label needs its whole row: the label's value is the row's name, and
// `rowNamed` finds the row. (The label's index counts only the segments drawn, so it cannot.)
export function nameOf(key: string) {
  return (entry: { payload?: Row }) => String(entry.payload?.[key] ?? "");
}

export function rowNamed(rows: Row[], key: string, name: unknown): Row | undefined {
  return rows.find((r) => String(r[key]) === String(name));
}

// A stack's total, written past the end of its last non-zero segment: give it to every series'
// LabelList `content`, with `valueAccessor={nameOf(key)}`; only the series that ends the row
// draws it.
export function stackTotal(rows: Row[], nameKey: string, keys: string[], key: string, format: (v: number) => string, horizontal = false) {
  return function StackTotal({ x, y, width, height, value }: LabelBox) {
    const row = rowNamed(rows, nameKey, value);
    if (!row) return null;
    const values = keys.map((k) => Number(row[k]) || 0);
    // a stack of nothing still says 0, at the first series
    const last = keys.filter((_, i) => values[i] > 0).pop() ?? keys[0];
    if (last !== key) return null;
    const total = values.reduce((a, b) => a + b, 0);
    const [bx, by, bw, bh] = [x, y, width, height].map(Number);
    return horizontal ? (
      <text x={bx + bw + 6} y={by + bh / 2} dy={4} className="bar-label">
        {format(total)}
      </text>
    ) : (
      <text x={bx + bw / 2} y={by - 6} textAnchor="middle" className="bar-label">
        {format(total)}
      </text>
    );
  };
}

// A count inside a stacked segment, only where the segment is wide enough to hold it.
export function SegmentCount({ x, y, width, height, value }: LabelBox) {
  const [bx, by, bw, bh] = [x, y, width, height].map(Number);
  if (!Number(value) || bw < 28) return null;
  return (
    <text x={bx + bw / 2} y={by + bh / 2} dy={4} textAnchor="middle" className="bar-label in-segment">
      {String(value)}
    </text>
  );
}

export function SeriesKey({ series }: { series: { name: string; color: string; dashed?: boolean }[] }) {
  return (
    <ul className="series-key" aria-label="Series">
      {series.map((s) => (
        <li key={s.name}>
          <i className={s.dashed ? "swatch dashed" : "swatch"} style={{ background: s.dashed ? undefined : s.color, borderColor: s.color }} />
          {s.name}
        </li>
      ))}
    </ul>
  );
}
