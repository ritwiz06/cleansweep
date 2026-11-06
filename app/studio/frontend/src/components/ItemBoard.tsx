import { useState } from "react";
import { STAGE_LABELS, itemsByStage, type Item, type ItemStage, type RunState } from "../state/fold";
import { Badge, Drawer, Empty, Status } from "./common";
import { StateChip } from "./states";

const COLUMNS: ItemStage[] = [
  "candidate",
  "investigating",
  "safe",
  "suggest",
  "dropped",
  "in_package",
  "kept",
  "rolled_back",
  "repaired",
];

function describe(e: { kind: string; payload: any }): string {
  const p = e.payload || {};
  if (e.kind === "tool_call") return `${p.tool}(${JSON.stringify(p.args || {}).slice(0, 160)})`;
  const result = typeof p.result === "string" ? p.result : JSON.stringify(p.result ?? p);
  return `${p.result_id ? p.result_id + " " : ""}${p.tool}: ${result.slice(0, 400)}`;
}

export function ItemDetail({ item, state }: { item: Item; state: RunState }) {
  const v = item.verdict;
  const lessons = (v?.lessons || []).map((id) => state.lessons.find((l) => l.id === id) || { id, reason: "(from an earlier run)", pattern: {} });
  return (
    <div className="item-detail">
      <dl className="facts">
        <dt>Unit</dt>
        <dd>
          <code>{item.unit}</code>
        </dd>
        <dt>Category</dt>
        <dd>{item.category}</dd>
        <dt>Lane</dt>
        <dd>{item.lane}</dd>
        <dt>Now</dt>
        <dd>
          <Status value={item.stage} />
          {item.pkg && <> in {item.pkg}</>}
        </dd>
      </dl>
      <h4>Path through the board</h4>
      <ol className="history">
        {item.history.map((h, i) => (
          <li key={i}>
            {h.t.toFixed(1)} s · {STAGE_LABELS[h.stage]}
          </li>
        ))}
      </ol>
      <h4>Verdict</h4>
      {v ? (
        <div>
          <p>
            <Status value={v.decision} /> by <code>{v.agent}</code>
            {v.confidence !== null && <> · confidence {v.confidence}</>}
          </p>
          <p>{v.reason}</p>
          <h4>Evidence</h4>
          {v.evidence.length ? (
            <ul className="evidence">
              {v.evidence.map((ev, i) => (
                <li key={i}>
                  {typeof ev === "string" ? ev : (
                    <>
                      {ev.result && <b>{ev.result} </b>}
                      {ev.tool && <code>{ev.tool}</code>} {ev.says || JSON.stringify(ev)}
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No evidence listed.</p>
          )}
          <h4>Evidence chain (the investigator's tool calls)</h4>
          {item.chain.length ? (
            <ol className="chain">
              {item.chain.map((e) => (
                <li key={e.id} className={e.kind}>
                  <span className="time">{e.t.toFixed(1)} s</span> {describe(e)}
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted">No tool calls recorded for this verdict.</p>
          )}
          <h4>Lessons cited</h4>
          {lessons.length ? (
            <ul>
              {lessons.map((l) => (
                <li key={l.id}>
                  <b>{l.id}</b>: {l.reason} <code>{JSON.stringify(l.pattern)}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None.</p>
          )}
        </div>
      ) : (
        <p className="muted">Not decided yet.</p>
      )}
    </div>
  );
}

export function ItemBoard({ state }: { state: RunState }) {
  const [open, setOpen] = useState<string | null>(null);
  const columns = itemsByStage(state);
  const shown = columns.skipped.length ? [...COLUMNS, "skipped" as ItemStage] : COLUMNS;
  if (!state.itemOrder.length) return <Empty>No candidates yet; the Auditor posts them after the baseline.</Empty>;
  const item = open ? state.items[open] : null;
  return (
    <>
      <div className="kanban" aria-label="Item board">
        {shown.map((stage) => (
          <div key={stage} className={`column stage-${stage} st-${stage}`}>
            <h4>
              <StateChip state={stage} label={STAGE_LABELS[stage]} /> <Badge>{columns[stage].length}</Badge>
            </h4>
            <div className="cards">
              {columns[stage].map((it) => (
                <button key={it.id} className="item-card" onClick={() => setOpen(it.id)} title={it.unit}>
                  <span className="unit">{it.unit}</span>
                  <span className="meta">
                    {it.category}
                    {it.pkg && ` · ${it.pkg}`}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {item && (
        <Drawer title={item.unit} onClose={() => setOpen(null)}>
          <ItemDetail item={item} state={state} />
        </Drawer>
      )}
    </>
  );
}
