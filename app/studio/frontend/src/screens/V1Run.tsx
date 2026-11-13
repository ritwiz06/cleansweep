import { api, useApi, type RunDetail, type Table } from "../api";
import { DiffView } from "../components/Code";
import { Async, Badge, Card, DataTable, Empty, ErrorBox, Loading, StatsRow, Status, seconds } from "../components/common";
import { Transport } from "../components/Transport";
import { V1_STAGES, V1_STAGE_LABELS, foldV1, type V1Event, type V1State } from "../state/foldV1";
import { useEvents, usePlayer } from "../state/hooks";

const JUDGE = /^llm judge: (\w+) \(confidence ([\d.]+|None)\)/;

function judge(evidence: string[]): [string, number | null] {
  for (const line of [...evidence].reverse()) {
    const m = JUDGE.exec(line);
    if (m) return [m[1], m[2] === "None" ? null : Number(m[2])];
  }
  return ["-", null];
}

function StageBar({ s }: { s: V1State }) {
  return (
    <div className="stage-bar" aria-label="Stages">
      {V1_STAGES.map((stage) => {
        const status = s.stages[stage] || "pending";
        return (
          <div key={stage} className={`stage ${status}`}>
            {status === "running" && <span className="spinner small" />}
            {V1_STAGE_LABELS[stage]}
            {status === "running" && ` ${Math.max(s.t - s.currentSince, 0).toFixed(0)} s`}
            {status === "done" && stage !== "done" && ` · ${seconds(s.stageSeconds[stage] || 0)}`}
          </div>
        );
      })}
    </div>
  );
}

function planTable(s: V1State): Table {
  const columns = ["lane", "category", "unit", "status", "judge", "confidence", "safe_score", "reason", "evidence"];
  const rows = s.items.map((item) => {
    let [decision, confidence] = judge(item.evidence || []);
    if (item.category === "format" && decision === "-") decision = "skipped (format)";
    const unit = item.unit.path + (item.unit.name ? `::${item.unit.name}` : "");
    return [
      item.lane,
      item.category,
      unit,
      s.statuses[item.item_id] || "",
      decision,
      confidence,
      s.scores[item.item_id] ?? item.safe_score,
      item.reason,
      (item.evidence || []).filter((e: string) => !e.startsWith("llm judge")).join("; "),
    ];
  });
  return { columns, rows };
}

function CheckCard({ card, units }: { card: any; units: Record<string, any> }) {
  const probes = card.probes;
  return (
    <div className="check-card">
      <div>
        <b>Check {card.n}</b> · {card.items.length} item(s)
        {card.seconds != null && ` · ${card.seconds} s`}{" "}
        {card.result ? <Status value={card.result} /> : <Badge tone="warn">checking</Badge>}
      </div>
      <ul>
        {card.items.map((id: string, i: number) => (
          <li key={id}>
            <code>{card.units?.[i]}</code> <span className="muted">({units[id]?.category || "?"})</span>
          </li>
        ))}
      </ul>
      {card.result && (
        <div className="small muted">
          Checks: compile, import,{" "}
          {card.tests ? `tests (${card.tests.passed} passed, ${card.tests.failed} failed)` : "tests"}
          {card.ast_equal != null && `, AST unchanged: ${card.ast_equal ? "yes" : "no"}`}
          {probes && `, probes: ${probes.n_cases} cases ${probes.same ? "agree" : `${probes.mismatches.length} differ`}`} · test runs so
          far: {card.test_runs}
        </div>
      )}
      {probes && !probes.same && (
        <div className="probe-catch">
          <b>The probes caught a behavior change:</b>
          <ul>
            {probes.mismatches.slice(0, 5).map((m: string) => (
              <li key={m}>
                <code>{m}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Hidden({ hidden }: { hidden: any }) {
  if (hidden === null) return <p className="muted">Runs after the Guard.</p>;
  if (!hidden.available) return <p>No hidden checks for this target.</p>;
  if (hidden.applied === false) return <p className="warn-text">The cleanup diff did not apply to a fresh copy, so nothing was checked.</p>;
  const before = new Set<string>(hidden.hidden_before.failed_ids);
  const after = new Set<string>(hidden.hidden_after.failed_ids);
  const flipped = [...before].filter((x) => !after.has(x)).concat([...after].filter((x) => !before.has(x)));
  return (
    <div>
      {hidden.behavior_changed ? (
        <p className="bad-text">
          <b>Behavior changed: yes</b> {flipped.join(", ")}
        </p>
      ) : (
        <p className="good-text">
          <b>Behavior changed: no</b>
        </p>
      )}
      {hidden.visible_new_failures?.length > 0 && <p className="warn-text">Visible tests broken: {hidden.visible_new_failures.join(", ")}</p>}
    </div>
  );
}

export function V1Run({ detail, live }: { detail: RunDetail; live: boolean }) {
  const feed = useEvents<V1Event>(detail.root, detail.path, live);
  const player = usePlayer(feed.events);
  const count = live ? feed.events.length : player.count;
  const s = foldV1(feed.events.slice(0, count));
  const score = useApi<{ score: any; toy_runs: Table | null }>(
    feed.done ? `score:${detail.root}/${detail.path}` : null,
    () => api("/api/run/score", { root: detail.root, path: detail.path }),
  );
  if (feed.error) return <ErrorBox error={feed.error} />;
  if (!live && !feed.done) return <Loading what="Loading the recording" />;
  const units = Object.fromEntries(s.items.map((i) => [i.item_id, i]));
  const end = feed.events.length ? feed.events[feed.events.length - 1].t : 0;
  const safeTotal = s.items.filter((i) => i.lane === "safe" && i.action !== "report_only").length;
  return (
    <div className="v1-run">
      {!live && <Transport player={player} total={feed.events.length} end={end} />}
      {s.run.run_id && (
        <p className="muted small">
          {s.run.run_id} · method {s.run.method} · judge {s.run.judge_mode} · model {s.run.model || "none"}
        </p>
      )}
      <StageBar s={s} />
      {s.current === "plan" && (
        <p className="small">
          <span className="spinner small" /> {s.llm.length ? `LLM judge working: request ${s.llm.length}, ${s.llm.filter((c) => c.seconds !== null).length} done` : "Running detectors"}
        </p>
      )}
      {s.error && <ErrorBox error={s.error} />}
      <div className="grid v1">
        <Card title="Reviewer plan">
          {s.items.length ? <DataTable table={planTable(s)} label="Reviewer plan" /> : <Empty>Waiting for the Reviewer...</Empty>}
        </Card>
        <Card title="Guard">
          <StatsRow
            label="Guard numbers"
            items={[
              ...(safeTotal > 0
                ? [
                    {
                      label: `Slop cleaned (items), ${Math.max(s.items.length - s.kept, 0)} still open`,
                      value: `${s.kept} / ${s.items.length}`,
                      lead: true,
                      share: s.kept / Math.max(s.items.length, 1),
                    },
                  ]
                : []),
              { label: "Kept", value: s.kept },
              { label: "Rolled back", value: s.rolledBack },
              { label: "Test runs", value: s.testRuns },
              { label: "Lines removed", value: s.linesRemoved },
            ]}
          />
          <div className="checks">
            {[...s.batches].reverse().map((card) => (
              <CheckCard key={`${card.n}-${card.start}`} card={card} units={units} />
            ))}
          </div>
        </Card>
      </div>
      <div className="grid two">
        <Card title="Diffs">
          {s.results.filter((r) => r.diff).length ? (
            s.results
              .filter((r) => r.diff)
              .map((r) => (
                <details key={r.item_id}>
                  <summary>
                    <Status value={r.status} /> {units[r.item_id]?.category} · {units[r.item_id]?.unit?.path}
                    {units[r.item_id]?.unit?.name ? `::${units[r.item_id].unit.name}` : ""}
                  </summary>
                  <DiffView text={r.diff} />
                </details>
              ))
          ) : (
            <Empty>Diffs appear when the Guard finishes.</Empty>
          )}
        </Card>
        <Card title="Hidden checks">
          <Hidden hidden={s.hidden} />
          <Async res={score} what="Scoring">
            {(d) =>
              d.score && s.report ? (
                <>
                  <h4>Outcome vs. answer key</h4>
                  <StatsRow items={[{ label: "Outcome accuracy", value: `${d.score.hits}/${d.score.total}` }]} />
                  <DataTable table={d.score.table} label="Outcome vs. answer key" />
                </>
              ) : null
            }
          </Async>
        </Card>
      </div>
      {s.logs.length > 0 && (
        <details>
          <summary>Run log ({s.logs.length} lines)</summary>
          <pre className="log" tabIndex={0}>{s.logs.map((e) => `${e.level} ${e.logger}: ${e.message}`).join("\n")}</pre>
        </details>
      )}
      <Card title="Toy repo runs so far">
        <Async res={score}>{(d) => (d.toy_runs ? <DataTable table={d.toy_runs} label="Toy repo runs" /> : <Empty>No saved runs in results/raw/toy/.</Empty>)}</Async>
      </Card>
    </div>
  );
}
