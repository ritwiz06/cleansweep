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
`--border`, `--grid`. One accent: `--accent` for links, focus rings and the selected tab, and
`--accent-fill` with `--accent-ink` text for filled controls (the primary button, a selected
segment). Outcome tones (verdicts, gauges): `--good`, `--warn`, `--bad`, `--info`, each with an
`-ink` variant for text; a verdict badge is the tone at 14% with its ink text. Phases and chart
series: `--series-1` … `--series-8`. A phase on the timeline is its series color as a bar on
top and a tint behind the text, so the label keeps the text color.

### Item states

Every candidate (a file, class, function or line range) is in one state. Each state has a color
(`--st-<state>`), a glyph and a label; the glyph and the label always appear with the color, so
no state is told by color alone. The hues are the Okabe–Ito set (plus violet for "in
package"), which stays distinct for the common color-vision deficiencies, darkened for the light
theme and lightened for the dark one until text in them reaches 4.5:1 on `--surface` and on their own 14% tint (the background of a state chip).

| State | Glyph | Light | Dark | Meaning |
|---|---|---|---|---|
| untouched | (none) | `#5f5e59` | `#a19f97` | no detector flagged it |
| candidate | ○ | `#006297` | `#56a8e0` | a detector flagged it |
| investigating | ◐ | `#8a5100` | `#e9a93a` | an Investigator is gathering evidence |
| safe | ◇ | `#186489` | `#79c4ec` | the Investigator cleared it; waiting for a package |
| suggest | ? | `#973e70` | `#dc93bb` | reported for a person to decide, not applied |
| dropped | ⊘ | `#5f5e59` | `#a19f97` | the Investigator said leave it |
| in package | ▣ | `#6a3fb0` | `#ac90e7` | in a work package being applied and checked |
| kept | ✓ | `#006b49` | `#3cc79b` | applied, every check passed, committed |
| rolled back | ↺ | `#9f3f00` | `#ff8f52` | a check failed; undone (a lesson was written) |

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
- Focus rings are always visible (2px `--accent`); every control has an accessible name, and a
  box that scrolls takes the focus so the keyboard can scroll it.
- Empty, loading and error states say what is missing in one line, with a button for what to
  do (try again, check again, open another screen).
- Anything an LLM judged carries an "LLM-judged" label.

## Screens

Every screen opens with the same header: the title (balanced, no orphan word), a one-line
description, the "What am I looking at?" button (a one-line popover; Escape closes it) and the
screen's actions on the right. Charts name their series above the plot, beside the title, and
write each bar's value (a stack's total) on the bar, so nobody reads values off an axis or
hunts in a legend. Home offers "Take the tour" (a six-step overlay over the demo app's
recording: the controls, the numbers, the phases, the project, the agents, what next; the arrow
keys move, Escape ends it) and "Try the demo" (the same recording in Replay).

Presentation mode works at 1280×720 and 1920×1080. A replay's presentation shows the project
tree or the agent graph (the Project / Agents switch, or G): the tree's rows grow and the item
at work carries its state in words; the graph zooms to fill its box, the agent at work is
filled with the accent and marked "at work", and the newest message is an accent arrow with its
type on it and a dot travelling along it. Evaluation has a Present button too: no sidebar,
larger type, taller charts.
