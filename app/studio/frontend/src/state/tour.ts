// The guided tour's geometry: where the card goes beside the part of the screen it explains.

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export const MARGIN = 16;
const GAP = 12;

// Below the target if the card fits there, else above, aligned with the target's left edge;
// else inside the target's top right corner (a tall target keeps its left side in view).
// Always inside the viewport.
export function placeCard(target: Box, card: { width: number; height: number }, view: { width: number; height: number }) {
  const below = target.top + target.height + GAP;
  const above = target.top - GAP - card.height;
  const clampLeft = (x: number) => Math.max(MARGIN, Math.min(x, view.width - MARGIN - card.width));
  if (below + card.height <= view.height - MARGIN) return { top: below, left: clampLeft(target.left), side: "below" as const };
  if (above >= MARGIN) return { top: above, left: clampLeft(target.left), side: "above" as const };
  const top = Math.max(MARGIN, Math.min(target.top + MARGIN, view.height - MARGIN - card.height));
  return { top, left: clampLeft(target.left + target.width - card.width - MARGIN), side: "inside" as const };
}

// The spotlight: the target with a little air around it, clipped to the viewport.
export function spotlight(target: Box, view: { width: number; height: number }, pad = 6): Box {
  const top = Math.max(target.top - pad, 4);
  const left = Math.max(target.left - pad, 4);
  const bottom = Math.min(target.top + target.height + pad, view.height - 4);
  const right = Math.min(target.left + target.width + pad, view.width - 4);
  return { top, left, width: Math.max(right - left, 0), height: Math.max(bottom - top, 0) };
}
