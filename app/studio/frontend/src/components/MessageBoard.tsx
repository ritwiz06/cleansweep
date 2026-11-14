import { useMemo, useState } from "react";
import { roleOf, type Message, type RunState } from "../state/fold";
import { plural } from "../state/labels";
import { ArtifactLink } from "./Artifact";
import { Badge, Empty } from "./common";

const SHOWN = 300;

export function summarize(m: Message): string {
  const b = m.body || {};
  switch (m.type) {
    case "task":
      return b.goal || "";
    case "verdict":
      return `${b.decision}: ${b.reason || ""}`;
    case "candidates":
      return `${(b.items || []).length} candidates`;
    case "blueprint":
      return `${(b.packages || []).length} work packages`;
    case "package_applied":
      return `${b.package}: ${(b.applied || []).length} applied, ${(b.not_applied || []).length} not applied`;
    case "test_result":
      return `${b.package}: ${b.ok ? "tests pass" : `new failures: ${(b.new_failures || []).join(", ")}`}`;
    case "validation":
      return `${b.package}: ${b.ok ? "checks pass" : "checks fail"}${b.probes ? `, ${plural(b.probes.n_cases, "probe case")}` : ""}`;
    case "baseline":
      return `${b.passed} passed, ${b.failed} failed, ${b.errors} errors`;
    case "failure":
      return `${b.package} failed at ${b.stage}`;
    case "repair":
      return `${b.package}: ${b.outcome}`;
    case "lesson":
      return `${b.lesson_id}: ${b.reason}`;
    case "final_check":
      return b.ok ? `final suite: ${b.passed} passed (baseline ${b.baseline_passed})` : "final suite has new failures";
    case "brief":
      return b.summary || "";
    case "report":
      return (b.files || []).join(", ");
    default:
      return JSON.stringify(b).slice(0, 160);
  }
}

export function MessageBoard({ state }: { state: RunState }) {
  const [type, setType] = useState("");
  const [agent, setAgent] = useState("");
  const [text, setText] = useState("");
  const types = useMemo(() => [...new Set(state.messages.map((m) => m.type))].sort(), [state.messages.length]);
  const shown = state.messages.filter(
    (m) =>
      (!type || m.type === type) &&
      (!agent || roleOf(m.sender) === agent || m.recipients.some((r) => roleOf(r) === agent)) &&
      (!text || summarize(m).toLowerCase().includes(text.toLowerCase())),
  );
  return (
    <div className="board">
      <div className="filters">
        <label>
          Type{" "}
          <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Message type">
            <option value="">all</option>
            {types.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          Agent{" "}
          <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
            <option value="">all</option>
            {Object.keys(state.agents).map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <input placeholder="Search messages" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search messages" />
        <span className="muted small">
          {shown.length} of {state.messages.length} messages
        </span>
      </div>
      {!shown.length ? (
        <Empty>No messages{state.messages.length ? " match the filters" : " yet"}.</Empty>
      ) : (
        <ol className="messages" reversed>
          {shown
            .slice(-SHOWN)
            .reverse()
            .map((m) => (
              <li key={m.eventId} className="message">
                <span className="time">{m.t.toFixed(1)} s</span>
                <span className="hyperedge">
                  <b className={`chip agent-chip squad-${roleOf(m.sender)}`}>{m.sender}</b>
                  <span className="arrow">→</span>
                  {m.recipients.map((r) => (
                    <span key={r} className="chip agent-chip">
                      {r}
                    </span>
                  ))}
                </span>
                <Badge tone="info">{m.type}</Badge>
                <span className="summary">{summarize(m)}</span>
                {m.artifacts.map((a) => (
                  <ArtifactLink key={a} id={a} />
                ))}
              </li>
            ))}
        </ol>
      )}
    </div>
  );
}
