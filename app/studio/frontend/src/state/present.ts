// Presentation mode's pacing: a fixed time per captioned step or slide, and where the space bar
// goes next.
import { annotateFile, type HunkNote } from "./annotate";
import type { CaptionStep } from "./caption";
import type { DiffFile } from "./diff";
import type { RunState } from "./fold";

// Fixed, readable speeds: every step gets the same time on screen whatever it took in the run.
export const STEP_MS = 1500;
export const SLIDE_MS = 5000;

// The next step that is a decision (the space bar), or the last step.
export function nextDecisionStep(steps: CaptionStep[], at: number): number {
  for (let k = at + 1; k < steps.length; k++) if (steps[k].decision) return k;
  return Math.max(steps.length - 1, 0);
}

export type Slide =
  | { kind: "summary"; first: boolean }
  | { kind: "change"; file: DiffFile; hunk: number; note: HunkNote; n: number; of: number };

// Before / after as slides: the summary, each change of the final diff, then the summary again.
export function afterSlides(files: DiffFile[], state: RunState): Slide[] {
  const changes = files.flatMap((file) => annotateFile(file, state).map((note, hunk) => ({ file, hunk, note })));
  return [
    { kind: "summary", first: true },
    ...changes.map((c, i) => ({ kind: "change" as const, ...c, n: i + 1, of: changes.length })),
    { kind: "summary", first: false },
  ];
}
