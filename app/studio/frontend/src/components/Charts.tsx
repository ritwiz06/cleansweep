// Shared chart pieces: the axis and tooltip styles, and the series names written above a chart,
// beside its title, instead of a legend under it.

export const AXIS = { fill: "var(--muted)", fontSize: 12 };
export const TOOLTIP = { background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" };

interface LabelBox {
  x?: number | string;
  y?: number | string;
  width?: number | string;
  height?: number | string;
  index?: number;
}

// A stack's total, written past the end of its last non-zero segment: give it to every series'
// LabelList `content`; only the series that ends the row draws it.
export function stackTotal(rows: Record<string, unknown>[], keys: string[], key: string, format: (v: number) => string, horizontal = false) {
  return function StackTotal({ x, y, width, height, index }: LabelBox) {
    const row = rows[index ?? -1];
    if (!row) return null;
    const values = keys.map((k) => Number(row[k]) || 0);
    const last = keys.filter((_, i) => values[i] > 0).pop();
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
