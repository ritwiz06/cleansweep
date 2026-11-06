// Item states as docs/studio_design.md draws them: a color, a glyph and a label, always together.

export const STATE_GLYPH: Record<string, string> = {
  untouched: "",
  candidate: "○",
  investigating: "◐",
  safe: "◇",
  suggest: "?",
  dropped: "⊘",
  in_package: "▣",
  kept: "✓",
  repaired: "✓",
  rolled_back: "↺",
  reverted: "↺",
  skipped: "·",
};

const LABEL: Record<string, string> = {
  dropped: "left alone",
  in_package: "in package",
  rolled_back: "rolled back",
  skipped: "not applied",
};

// The statuses a package or verdict reports that are item states under another name.
const ALIAS: Record<string, string> = { drop: "dropped", "rolled back": "rolled_back" };

export function stateOf(value: string): string | null {
  const key = ALIAS[value] || value;
  return key in STATE_GLYPH ? key : null;
}

export function stateLabel(state: string): string {
  return LABEL[state] || state.replace(/_/g, " ");
}

export function StateChip({ state, label }: { state: string; label?: string }) {
  const glyph = STATE_GLYPH[state];
  return (
    <span className={`state-chip st-${state}`} data-state={state}>
      {glyph && (
        <span className="state-glyph" aria-hidden>
          {glyph}
        </span>
      )}
      {label ?? stateLabel(state)}
    </span>
  );
}

export const LEGEND_STATES = ["untouched", "candidate", "investigating", "safe", "suggest", "in_package", "kept", "rolled_back"];

export function StateLegend({ states = LEGEND_STATES }: { states?: string[] }) {
  return (
    <div className="state-legend" aria-label="State legend">
      {states.map((s) => (
        <StateChip key={s} state={s} />
      ))}
    </div>
  );
}
