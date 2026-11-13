import { plural } from "../state/labels";
import { Status } from "./common";

// What a finished run did, in words ("5 kept · 1 rolled back · −47 lines"). A badge appears only
// when the result is not the usual one (not verified, stopped, nothing applied...).
export function RunOutcome({
  verdict,
  kept,
  rolledBack,
  lines,
  finished = true,
}: {
  verdict: string | null | undefined;
  kept?: number | null;
  rolledBack?: number | null;
  lines?: number | null;
  finished?: boolean;
}) {
  const parts: string[] = [];
  if (kept !== undefined && kept !== null) parts.push(`${kept} kept`);
  if (rolledBack) parts.push(`${rolledBack} rolled back`);
  if (lines) parts.push(`−${plural(lines, "line")}`);
  const unusual = Boolean(verdict) && verdict !== "everything runs";
  return (
    <span className="run-outcome" title={verdict || undefined}>
      {unusual && <Status value={verdict} />}
      {parts.length > 0 ? (
        <span className="outcome-text">{parts.join(" · ")}</span>
      ) : (
        !unusual && <span className="muted">{verdict || (finished ? "finished" : "unfinished")}</span>
      )}
    </span>
  );
}
