import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import type { RunState, StudioEvent } from "../state/fold";
import type { Player } from "../state/hooks";
import { seconds } from "./common";

// The run's steps in plain words, in order; a step back revisits one of them.
export const STEPS: [string, string][] = [
  ["ONBOARD", "Onboard"],
  ["BASELINE", "Baseline"],
  ["AUDIT", "Audit"],
  ["INVESTIGATE", "Investigate"],
  ["PLAN", "Plan"],
  ["EXECUTE", "Execute"],
  ["FINAL_VERIFY", "Verify"],
  ["REPORT", "Report"],
];

const KEYS: Record<string, (count: number, total: number) => number> = {
  ArrowRight: (c) => c + 1,
  ArrowLeft: (c) => c - 1,
  PageDown: (c) => c + 10,
  PageUp: (c) => c - 10,
  Home: () => 0,
  End: (_, total) => total,
};

// The replay's slider: a click or a drag goes to that point of the run; the arrow keys move one
// event, Page Up / Page Down ten, Home and End to either end.
function Scrubber({ player, total }: { player: Player; total: number }) {
  const dragging = useRef(false);
  const share = total ? player.count / total : 0;
  const seekAt = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    player.setCount(Math.round(Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1) * total));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const move = KEYS[e.key];
    if (!move) return;
    player.setCount(Math.max(0, Math.min(total, move(player.count, total))));
    e.preventDefault();
  };
  return (
    <div
      className="run-scrub"
      role="slider"
      tabIndex={0}
      aria-label="Scrubber"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={player.count}
      aria-valuetext={`event ${player.count} of ${total}, ${seconds(player.clock)}`}
      onKeyDown={onKey}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        seekAt(e);
      }}
      onPointerMove={(e) => dragging.current && seekAt(e)}
      onPointerUp={() => (dragging.current = false)}
    >
      <span className="scrub-track">
        <span className="scrub-fill" style={{ width: `${share * 100}%` }} />
      </span>
      <span className="scrub-thumb" style={{ left: `${share * 100}%` }} />
    </div>
  );
}

// One sticky band over a run: Play, Next decision and the slider, the slop removed, and the steps
// with the current one in bold.
export function RunBand({ state, events, player }: { state: RunState; events: StudioEvent[]; player: Player | null }) {
  const total = events.length;
  const end = total ? events[total - 1].t : 0;
  const atEnd = player ? player.count >= total : true;
  const share = state.candidates ? state.applied / state.candidates : 0;
  const now = state.finished ? STEPS.length : STEPS.findIndex(([p]) => p === state.phase);
  const steps = (
    <ol className="run-steps" aria-label="Steps">
      {STEPS.map(([phase, label], i) => (
        <li key={phase} className={i < now ? "done" : i === now ? "current" : undefined} aria-current={i === now ? "step" : undefined}>
          {i < now && <span aria-hidden>✓ </span>}
          {label}
        </li>
      ))}
    </ol>
  );
  // a replay has its controls on the first line and the steps under them; a live run, one line
  return (
    <section className="run-band" aria-label={player ? "Replay controls" : "Run progress"} data-sticky>
      <div className="band-top">
        {!player && steps}
        {player && (
          <div className="band-controls">
            <button
              className="primary"
              onClick={() => {
                if (atEnd) player.setCount(0);
                player.setPlaying(!player.playing);
              }}
            >
              <span aria-hidden>{player.playing ? "❚❚" : "▶"}</span> {player.playing ? "Pause" : "Play"}
            </button>
            <button onClick={player.nextDecision} disabled={atEnd}>
              Next decision <span aria-hidden>⏭</span>
            </button>
          </div>
        )}
        {player && <Scrubber player={player} total={total} />}
        {player && (
          <span className="band-clock">
            {seconds(player.clock)} / {seconds(end)}
          </span>
        )}
        <div className="band-lead">
          {state.candidates ? (
            <span>
              Removed <b className="band-lead-value">{state.applied}</b> of {state.candidates}
            </span>
          ) : (
            <span>No candidates yet</span>
          )}
          <span className="bar" role="meter" aria-label="Slop removed" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}>
            <span className="fill tone-good" style={{ width: `${share * 100}%` }} />
          </span>
        </div>
      </div>
      {player && steps}
    </section>
  );
}
