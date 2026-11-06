# Studio design rules

One set of tokens for every Studio screen. They live once, as CSS variables at the top of
`app/studio/frontend/src/styles.css`; components use the variables, never raw sizes or colors.
Studio is presented at 1280×720 on a projector, so the rules favor legibility over density.

## Type scale

| Token | Size | Used for |
|---|---|---|
| `--text-xs` | 12px | badges, meta lines, axis labels; the smallest text anywhere |
| `--text-sm` | 13px | tables, code, diffs, trees |
| `--text-md` | 14px | body text, buttons, form fields, card titles (bold) |
| `--text-lg` | 16px | section headings, the brand, gauge values |
| `--text-xl` | 20px | screen titles, stat values |
| `--text-2xl` | 28px | presentation captions, the metric numbers of before / after |
| `--text-3xl` | 40px | presentation mode's headline |

Presentation mode raises the whole scale (15, 17, 19, 22, 28, 34 and 46px) and hides the sidebar,
so the same components read from the back of a room.

Line height 1.45 for text, 1.35 for code. Numbers in tables and metrics use tabular figures.
Weights: 400 for text, 600 for labels and buttons, 700 for titles and values.

## Spacing scale

`--space-0` 2px (hairline gaps), `--space-1` 4px, `--space-2` 8px, `--space-3` 12px,
`--space-4` 16px, `--space-5` 24px, `--space-6` 32px. Padding inside a card is `--space-3`;
the gap between cards is `--space-3`; a screen's edge is `--space-4` to `--space-5`.
Radii: `--radius-sm` 4px (chips, marks), `--radius` 6px (controls), `--radius-lg` 8px (cards).

## Colors

Surfaces and text: `--page`, `--surface`, `--surface-2`, `--text`, `--text-2`, `--muted`,
`--border`, `--grid`, `--accent`. Outcome tones (verdicts, gauges): `--good`, `--warn`,
`--bad`, `--info`, each with an `-ink` variant for text. Phases and chart series:
`--series-1` … `--series-8`.

### Item states

Every candidate (a file, class, function or line range) is in one state. Each state has a color
(`--st-<state>`), a glyph and a label; the glyph and the label always appear with the color, so
no state is told by color alone. The hues are the Okabe–Ito set (plus violet for "in
package"), which stays distinct for the common color-vision deficiencies, darkened for the light
theme and lightened for the dark one until text in them reaches 4.5:1 on `--surface`.

| State | Glyph | Light | Dark | Meaning |
|---|---|---|---|---|
| untouched | (none) | `#6f6d68` | `#9a988f` | no detector flagged it |
| candidate | ○ | `#00679f` | `#56a8e0` | a detector flagged it |
| investigating | ◐ | `#965800` | `#e9a93a` | an Investigator is gathering evidence |
| safe | ◇ | `#1a6a92` | `#79c4ec` | the Investigator cleared it; waiting for a package |
| suggest | ? | `#a8457c` | `#dc93bb` | reported for a person to decide, not applied |
| dropped | ⊘ | `#6f6d68` | `#9a988f` | the Investigator said leave it |
| in package | ▣ | `#6a3fb0` | `#a98be6` | in a work package being applied and checked |
| kept | ✓ | `#00744f` | `#3cc79b` | applied, every check passed, committed |
| rolled back | ↺ | `#ad4500` | `#ff8f52` | a check failed; undone (a lesson was written) |

"Repaired" is kept (✓) with the label "repaired"; "reverted" (undone in FINAL VERIFY) is rolled
back (↺) with the label "reverted"; "skipped" (not applied) is untouched with the label.
Backgrounds use the state color at 14% (`color-mix`), so text on them keeps the page's contrast.

### Agents

Each of the eleven roles (Manager, Explorer, Auditor, Investigator, Planner, Engineer, Tester,
Validator, Fixer, Reporter, and the single agent of the `single_agent` ablation) has one inline
SVG icon drawn in `currentColor`, always with its name beside it or as its accessible label.
The squad decides the icon's tint: Manager `--series-7`, research `--series-1`, development
`--series-3`.

## Light and dark

`:root` holds the light theme and `:root[data-theme="dark"]` the dark one; the theme button
switches them and the choice is remembered. Every token has both values. Text contrast is at
least 4.5:1 and marks at least 3:1 on `--surface` in both themes.

## Motion

`--motion-fast` 120ms (hover, focus), `--motion` 200ms (state changes, bars),
`--ease` `cubic-bezier(0.2, 0, 0, 1)`. Motion only shows a change; nothing loops except the
spinner, the current phase's pulse and a message travelling on the agent graph. With
`prefers-reduced-motion: reduce` every animation and transition is off, charts skip their
entry animation and the agent graph shows messages without the travelling dot. Replay speed
is the reader's choice (1–50×), except in presentation mode, where it is fixed: 1.5 s per
captioned step of a run and 5 s per before / after slide, whatever the step took in the run.

## Legibility at 1280×720

- No text under 12px; code, trees and diffs at 13px; titles at 20px.
- No horizontal page scroll: wide content (tables, diffs, trees) scrolls inside its card.
- Long paths keep their file name: they are cut at the start (`…/cli/main.py`) with the whole
  path in the tooltip.
- A state, an outcome or an agent is never shown by color alone: glyph, label or icon too.
- Focus rings are always visible (2px `--accent`); every control has an accessible name.
- Empty, loading and error states say what is missing and what to do, in one line.
- Anything an LLM judged carries an "LLM-judged" label.
