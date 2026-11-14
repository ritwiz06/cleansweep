import { createContext, useContext, useEffect, type ReactNode } from "react";

// The App's theme switch, for the presentation bar (the sidebar is hidden there).
export const ThemeToggle = createContext<{ dark: boolean; toggle: () => void }>({ dark: false, toggle: () => undefined });

// Presentation mode's frame: a bar with the title, the position and the controls, and the keys:
// space or Page Down goes to the next decision, Shift+space or Page Up back, the arrows one
// step, P plays or pauses, Escape leaves.
export function PresentShell({
  title,
  position,
  progress,
  playing,
  onPlay,
  onNext,
  onPrev,
  onStep,
  exit,
  nextLabel = "Next decision",
  extra,
  children,
}: {
  extra?: ReactNode;
  title: ReactNode;
  position: ReactNode;
  progress: number;
  playing: boolean;
  onPlay: () => void;
  onNext: () => void;
  onPrev: () => void;
  onStep?: (delta: number) => void;
  exit: string;
  nextLabel?: string;
  children: ReactNode;
}) {
  const theme = useContext(ThemeToggle);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.("input, select, textarea")) return;
      const back = e.shiftKey && e.key === " ";
      if (e.key === " " || e.key === "PageDown" || e.key === "PageUp") {
        if (back || e.key === "PageUp") onPrev();
        else onNext();
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        (onStep || ((d: number) => (d > 0 ? onNext() : onPrev())))(e.key === "ArrowRight" ? 1 : -1);
      } else if (e.key === "p" || e.key === "P") onPlay();
      else if (e.key === "Escape") window.location.hash = exit;
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  // a clicked button would take the next space bar press as a click: let go of the focus
  const click = (action: () => void) => (e: { currentTarget: HTMLButtonElement }) => {
    action();
    e.currentTarget.blur();
  };
  return (
    <div className="present-shell">
      <header className="present-bar" aria-label="Presentation controls">
        <h2>{title}</h2>
        <span className="present-pos">{position}</span>
        {extra}
        <button className="primary" onClick={click(onPlay)}>
          <span aria-hidden>{playing ? "❚❚" : "▶"}</span> {playing ? "Pause" : "Play"}
        </button>
        <button onClick={click(onNext)} title="space bar">
          {nextLabel} <kbd>Space</kbd>
        </button>
        <button onClick={click(theme.toggle)} aria-label="Switch theme" title="Switch theme">
          <span aria-hidden>{theme.dark ? "☀" : "☾"}</span>
        </button>
        <a className="button present-exit" href={exit}>
          Exit <kbd>Esc</kbd>
        </a>
      </header>
      <div className="present-progress" role="progressbar" aria-label="Progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
        <div style={{ width: `${progress * 100}%` }} />
      </div>
      <section className="present-main">{children}</section>
    </div>
  );
}
