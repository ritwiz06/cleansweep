import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { placeCard, scrollDelta, spotlight, type Box } from "../state/tour";

export interface TourStep {
  target: string; // a CSS selector for the part of the screen the step explains
  title: string;
  text: string;
  enter?: () => void; // gets the screen ready (a tab, a moment of the recording)
}

const CARD = { width: 380, height: 190 };

function viewport() {
  return { width: window.innerWidth, height: window.innerHeight };
}

// A short guided overlay: a spotlight on one part of the screen and a card that explains it.
// Next and Back move through the steps (or the arrow keys); Escape or "Skip tour" ends it.
export function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const [at, setAt] = useState(0);
  const [spot, setSpot] = useState<Box | null>(null);
  const [card, setCard] = useState({ top: 0, left: 0 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[at];
  const last = at === steps.length - 1;

  const measure = useCallback(() => {
    const view = viewport();
    const el = document.querySelector(step.target);
    const size = cardRef.current ? { width: cardRef.current.offsetWidth, height: cardRef.current.offsetHeight } : CARD;
    if (!el) {
      setSpot(null);
      setCard({ top: (view.height - size.height) / 2, left: (view.width - size.width) / 2 });
      return;
    }
    const r = el.getBoundingClientRect();
    const target = { top: r.top, left: r.left, width: r.width, height: r.height };
    setSpot(spotlight(target, view));
    setCard(placeCard(target, size, view));
  }, [step.target]);

  useEffect(() => {
    step.enter?.();
    // the screen redraws after enter(); measure once it has
    const frame = requestAnimationFrame(() => {
      const el = document.querySelector(step.target);
      if (el) {
        const r = el.getBoundingClientRect();
        const card = cardRef.current?.offsetHeight ?? CARD.height;
        window.scrollBy(0, scrollDelta({ top: r.top, left: r.left, width: r.width, height: r.height }, card, window.innerHeight));
      }
      measure();
      nextRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [at]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  // the focus goes back where it was when the tour ends
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && !last) setAt(at + 1);
      else if (e.key === "ArrowLeft" && at > 0) setAt(at - 1);
      else if (e.key === "Tab") {
        // the focus stays inside the card while the tour is open
        const buttons = [...(cardRef.current?.querySelectorAll<HTMLButtonElement>("button") || [])];
        const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = i < 0 ? buttons[0] : buttons[(i + (e.shiftKey ? buttons.length - 1 : 1)) % buttons.length];
        next?.focus();
      } else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  return createPortal(
    <div className="tour">
      <div className="tour-scrim" onClick={(e) => e.stopPropagation()} />
      {spot && <div className="tour-spot" style={spot} aria-hidden />}
      <div
        ref={cardRef}
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-text"
        style={{ top: card.top, left: card.left }}
      >
        <div className="tour-step">
          Step {at + 1} of {steps.length}
        </div>
        <div className="tour-dots" aria-hidden>
          {steps.map((_, i) => (
            <span key={i} className={i <= at ? "done" : ""} />
          ))}
        </div>
        <h3 id="tour-title">{step.title}</h3>
        <p id="tour-text">{step.text}</p>
        <div className="tour-buttons">
          <button type="button" className="link skip" onClick={onClose}>
            {last ? "Close" : "Skip tour"}
          </button>
          {at > 0 && (
            <button type="button" onClick={() => setAt(at - 1)}>
              Back
            </button>
          )}
          <button ref={nextRef} type="button" className="primary" onClick={() => (last ? onClose() : setAt(at + 1))}>
            {last ? "Finish" : "Next"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
