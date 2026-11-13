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
// Always inside the viewport, and below `inset` (a sticky bar at the top of the screen).
export function placeCard(target: Box, card: { width: number; height: number }, view: { width: number; height: number }, inset = 0) {
  const below = target.top + target.height + GAP;
  const above = target.top - GAP - card.height;
  const clampLeft = (x: number) => Math.max(MARGIN, Math.min(x, view.width - MARGIN - card.width));
  if (below + card.height <= view.height - MARGIN) return { top: below, left: clampLeft(target.left), side: "below" as const };
  if (above >= MARGIN + inset) return { top: above, left: clampLeft(target.left), side: "above" as const };
  const top = Math.max(MARGIN + inset, Math.min(target.top + MARGIN, view.height - MARGIN - card.height));
  return { top, left: clampLeft(target.left + target.width - card.width - MARGIN), side: "inside" as const };
}

// How far to scroll so the target and the card under it fit on screen together, centred in the
// part of the screen under `inset` (a sticky bar); a target too tall for that goes to the top
// of that part.
export function scrollDelta(target: Box, cardHeight: number, viewHeight: number, inset = 0): number {
  const room = viewHeight - inset;
  const block = target.height + GAP + cardHeight;
  if (block <= room - 2 * MARGIN) return target.top - (inset + (room - block) / 2);
  return target.top - (inset + MARGIN);
}

// The dimmed screen around a spotlight, as four rectangles (one huge shadow is not drawn
// everywhere by every browser).
export function dimAround(spot: Box, view: { width: number; height: number }): Box[] {
  const bottom = spot.top + spot.height;
  const right = spot.left + spot.width;
  return [
    { top: 0, left: 0, width: view.width, height: spot.top },
    { top: bottom, left: 0, width: view.width, height: Math.max(view.height - bottom, 0) },
    { top: spot.top, left: 0, width: spot.left, height: spot.height },
    { top: spot.top, left: right, width: Math.max(view.width - right, 0), height: spot.height },
  ];
}

// The spotlight: the target with a little air around it, clipped to the viewport.
export function spotlight(target: Box, view: { width: number; height: number }, pad = 6): Box {
  const top = Math.max(target.top - pad, 4);
  const left = Math.max(target.left - pad, 4);
  const bottom = Math.min(target.top + target.height + pad, view.height - 4);
  const right = Math.min(target.left + target.width + pad, view.width - 4);
  return { top, left, width: Math.max(right - left, 0), height: Math.max(bottom - top, 0) };
}
