import type { Player } from "../state/hooks";
import { seconds } from "./common";

export function Transport({ player, total, end }: { player: Player; total: number; end: number }) {
  const atEnd = player.count >= total;
  return (
    <div className="transport" aria-label="Replay controls">
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
      <input
        type="range"
        className="scrubber"
        min={0}
        max={total}
        value={player.count}
        onChange={(e) => player.setCount(Number(e.target.value))}
        aria-label="Scrubber"
      />
      <span className="small clock">
        {seconds(player.clock)} / {seconds(end)} · event {player.count} of {total}
      </span>
      <span className="transport-divider" aria-hidden />
      <label className="speed">
        Speed{" "}
        <input
          type="range"
          min={1}
          max={50}
          value={player.speed}
          onChange={(e) => player.setSpeed(Number(e.target.value))}
          aria-label="Speed"
        />{" "}
        <b>{player.speed}×</b>
      </label>
    </div>
  );
}
