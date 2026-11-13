import type { RunDetail } from "../api";
import { PHASES, type Decision, type RunState, type StudioEvent } from "../state/fold";
import type { Player } from "../state/hooks";
import { countAt } from "../state/replay";
import { seconds } from "./common";
import { PhaseTimeline } from "./PhaseTimeline";

const DONE = ["kept", "rolled_back", "repaired", "reverted", "skipped"];

// One sticky band over a run: the playback controls and the slop cleaned, the phase timeline
// (which is also the scrubber), and one line with the rest of the numbers.
export function RunBand({
  state,
  events,
  detail,
  player,
  onDecision,
}: {
  state: RunState;
  events: StudioEvent[];
  detail: RunDetail | null;
  player: Player | null;
  onDecision: (d: Decision) => void;
}) {
  const total = events.length;
  const end = total ? events[total - 1].t : 0;
  const atEnd = player ? player.count >= total : true;
  const packages = Object.values(state.packages);
  const done = packages.filter((p) => DONE.includes(p.status)).length;
  const kept = packages.filter((p) => p.status === "kept" || p.status === "repaired").length;
  const rolledBack = packages.filter((p) => p.status === "rolled_back" || p.status === "reverted").length;
  const stats = detail?.report?.stats || {};
  // the events miss runs a step makes without a message; a finished run has the exact count
  const testRuns = typeof stats.test_runs === "number" ? stats.test_runs : state.testRuns;
  const minutes = Math.round((state.t / 60) * 10) / 10;
  const of = (used: number, limit?: number) => (limit ? `${used}/${limit}` : `${used}`);
  const now = state.phase && !state.finished ? PHASES.indexOf(state.phase as (typeof PHASES)[number]) : -1;
  const next = now >= 0 ? PHASES.slice(now + 1).find((p) => p !== "DONE") : undefined;
  const share = state.candidates ? state.applied / state.candidates : 0;
  const meta = [
    `${of(done, state.packageOrder.length || undefined)} packages done`,
    `${kept} kept`,
    `${rolledBack} rolled back`,
    `${of(testRuns, state.budget.test_runs)} test runs`,
    `${of(state.llmCalls, state.budget.llm_calls)} LLM calls`,
    `${of(minutes, state.budget.minutes)} min`,
  ];
  return (
    <section className="run-band" aria-label={player ? "Replay controls" : "Run progress"} data-sticky>
      <div className="band-top">
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
            <button onClick={player.stepOne} disabled={atEnd}>
              Step
            </button>
            <button onClick={player.nextDecision} disabled={atEnd}>
              Next decision <span aria-hidden>⏭</span>
            </button>
            <button onClick={() => player.setCount(total)} disabled={atEnd} aria-label="Jump to the end" title="Jump to the end">
              End
            </button>
          </div>
        )}
        <div className="band-lead" title="edits applied of the candidates found">
          <span className="band-lead-value">
            {state.applied}
            <span className="stat-of"> / {state.candidates}</span>
          </span>
          <span className="band-lead-label">slop cleaned</span>
          <span className="bar" role="meter" aria-label="Slop cleaned" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}>
            <span className="fill tone-good" style={{ width: `${share * 100}%` }} />
          </span>
        </div>
        <span className="band-clock">
          {player ? `${seconds(player.clock)} / ${seconds(end)} · event ${player.count} of ${total}` : `${total} events so far`}
        </span>
        {player && (
          <label className="speed">
            Speed{" "}
            <input type="range" min={1} max={50} value={player.speed} onChange={(e) => player.setSpeed(Number(e.target.value))} aria-label="Speed" />{" "}
            <b>{player.speed}×</b>
          </label>
        )}
      </div>
      <PhaseTimeline
        state={state}
        onDecision={onDecision}
        seek={
          player
            ? {
                clock: player.clock,
                count: player.count,
                total,
                toTime: (t) => player.setCount(countAt(events, t)),
                toCount: player.setCount,
              }
            : undefined
        }
      />
      <p className="band-meta">
        {meta.join(" · ")}
        {next && <span className="muted"> · next: {next.replace("_", " ")}</span>}
        {state.backSteps > 0 && <span className="bad-text"> · ↩ {state.backSteps} step back{state.backSteps > 1 ? "s" : ""}</span>}
      </p>
    </section>
  );
}
