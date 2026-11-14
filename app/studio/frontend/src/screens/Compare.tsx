import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, runHash, useApi, type RunDetail, type RunRow } from "../api";
import { TOOLTIP } from "../components/Charts";
import { ANIMATE, Async, Card, Empty, PageHeader, ShowMore, seconds } from "../components/common";
import { RunOutcome } from "../components/RunOutcome";
import { formatNumber } from "../state/labels";
import { PHASES } from "../state/fold";
import { runTitle, targetName } from "../state/names";
import { useRuns } from "./Runs";

const SERIES = ["var(--series-1)", "var(--series-2)"];

function key(r: { root: string; path: string }) {
  return `${r.root}:${r.path}`;
}

function split(value: string | null): { root: string; path: string } | null {
  if (!value) return null;
  const i = value.indexOf(":");
  return i > 0 ? { root: value.slice(0, i), path: value.slice(i + 1) } : null;
}

function numbers(d: RunDetail): Record<string, string | number | null> {
  const s = d.report?.stats || {};
  const a = s.agentic || {};
  const pk = (a.packages || []) as { status: string }[];
  return {
    result: a.verdict ?? (d.report ? "finished" : null),
    method: d.report?.method ?? d.mode,
    candidates: s.items_total ?? null,
    "edits kept": (s.items_kept ?? 0) + (s.items_repaired ?? 0),
    "rolled back": s.items_rolled_back ?? null,
    "lines removed": s.lines_removed ?? null,
    "files removed": s.files_removed ?? null,
    "test runs": s.test_runs ?? null,
    "LLM calls": s.llm_calls ?? null,
    tokens: s.prompt_tokens !== undefined ? s.prompt_tokens + s.completion_tokens : null,
    time: s.wall_seconds ?? null,
    "packages kept": pk.length ? pk.filter((p) => p.status === "kept").length : null,
    "packages rolled back": pk.length ? pk.filter((p) => p.status === "rolled_back").length : null,
    "step backs": a.back_steps ? Object.values(a.back_steps as Record<string, number>).reduce((x, y) => x + y, 0) : null,
    "verdicts safe / suggest / drop": a.decisions ? `${a.decisions.safe} / ${a.decisions.suggest} / ${a.decisions.drop}` : null,
    lessons: a.lessons ? a.lessons.length : null,
  };
}

// A run's letter in its series color, as on the chart.
function RunTag({ which }: { which: "A" | "B" }) {
  return <span className={`run-tag run-${which.toLowerCase()}`}>{which}</span>;
}

function show(key: string, value: string | number | null | undefined) {
  if (value === null || value === undefined) return "-";
  if (key === "time" && typeof value === "number") return seconds(value);
  return typeof value === "number" ? formatNumber(value) : value;
}

// The rows worth pointing at; "Show all the numbers" has the rest.
const MAIN = ["result", "edits kept", "rolled back", "lines removed", "test runs", "LLM calls", "time"];

// B minus A for a number both runs have, signed; nothing for text.
function difference(key: string, a: unknown, b: unknown) {
  if (typeof a !== "number" || typeof b !== "number") return "";
  const d = b - a;
  if (d === 0) return <span className="muted">0</span>;
  const size = key === "time" ? seconds(Math.abs(d)) : formatNumber(Math.abs(d));
  return `${d > 0 ? "+" : "−"}${size}`;
}

// The two runs in one sentence: what each removed and how long it took.
function compareSentence(both: (RunDetail | null | undefined)[]): string | null {
  const [a, b] = both;
  if (!a || !b) return null;
  const say = (d: RunDetail) => {
    const s = d.report?.stats || {};
    const lines = typeof s.lines_removed === "number" ? `${formatNumber(s.lines_removed)} lines` : "an unknown number of lines";
    return { name: targetName(d.target) || d.name, lines, time: typeof s.wall_seconds === "number" ? seconds(s.wall_seconds) : null };
  };
  const [x, y] = [say(a), say(b)];
  const time = (t: string | null) => (t ? ` in ${t}` : "");
  return `B, ${y.name}, removed ${y.lines}${time(y.time)}; A, ${x.name}, removed ${x.lines}${time(x.time)}.`;
}

function CompareTable({ both, keys, label }: { both: (RunDetail | null | undefined)[]; keys?: string[]; label: string }) {
  const rows = both.map((d) => (d ? numbers(d) : {}));
  return (
    <div className="table-wrap" tabIndex={0}>
      <table className="data compare" aria-label={label}>
        <thead>
          <tr>
            <th />
            {both.map((d, i) => (
              <th key={i} className="num">
                <RunTag which={i ? "B" : "A"} /> <span title={d?.name}>{d && runTitle(d)}</span> {d && <a href={runHash(d)}>replay</a>}
              </th>
            ))}
            <th className="num">B − A</th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(rows[0])
            .filter((k) => !keys || keys.includes(k))
            .map((k) => (
              <tr key={k}>
                <th>{k.charAt(0).toUpperCase() + k.slice(1)}</th>
                {rows.map((r, i) => (
                  <td key={i} className="num">
                    {k === "result" ? <RunOutcome verdict={r[k] as string} /> : show(k, r[k])}
                  </td>
                ))}
                <td className="num">{difference(k, rows[0][k], rows[1][k])}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function Picker({ label, value, runs, onChange }: { label: string; value: string; runs: RunRow[]; onChange: (v: string) => void }) {
  return (
    <label>
      {label}{" "}
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        <option value="">pick a run</option>
        {runs.map((r) => (
          <option key={key(r)} value={key(r)} title={r.name}>
            {runTitle(r)}
            {r.root === "replay" ? " · shipped recording" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function useDetail(run: { root: string; path: string } | null) {
  return useApi<RunDetail>(run ? key(run) : null, () => api("/api/run", run!));
}

export function Compare({ a, b, onChange }: { a: string; b: string; onChange: (a: string, b: string) => void }) {
  const runs = useRuns();
  const left = useDetail(split(a));
  const right = useDetail(split(b));
  const both = [left.data, right.data];
  const phaseData = PHASES.filter((p) => p !== "DONE").map((p) => ({
    phase: p.charAt(0) + p.slice(1).toLowerCase().replace("_", " "),
    A: left.data?.report?.stats?.agentic?.phase_seconds?.[p] ?? 0,
    B: right.data?.report?.stats?.agentic?.phase_seconds?.[p] ?? 0,
  }));
  const shipped = (runs.data || []).filter((r) => r.root === "replay" && r.kind === "v2");
  const example = shipped.length > 1 ? { label: "Compare two recordings", onClick: () => onChange(key(shipped[0]), key(shipped[1])) } : undefined;
  return (
    <div className="screen">
      <PageHeader
        title="Compare two runs"
        description="Two runs side by side: what each removed, what it cost, and its time per phase."
        help="Pick a run for A and one for B. Each row is the same number for both runs; the chart shows where each spent its time."
      />
      <Async res={runs} what="Finding runs">
        {(rows) => {
          const choices = rows.filter((r) => r.kind !== "watch");
          return (
            <div className="filters">
              <Picker label="Run A" value={a} runs={choices} onChange={(v) => onChange(v, b)} />
              <Picker label="Run B" value={b} runs={choices} onChange={(v) => onChange(a, v)} />
            </div>
          );
        }}
      </Async>
      {!a || !b ? (
        <Empty action={example}>Pick two runs to see them side by side.</Empty>
      ) : (
        <>
          <Card title="Side by side">
            <Async res={left}>
              {() => (
                <Async res={right}>
                  {() => (
                    <>
                      <p className="takeaway">{compareSentence(both)}</p>
                      <CompareTable both={both} keys={MAIN} label="Comparison" />
                      <ShowMore label="Show all the numbers">
                        <CompareTable both={both} label="All the numbers" />
                      </ShowMore>
                    </>
                  )}
                </Async>
              )}
            </Async>
          </Card>
          <Card title="Time per phase">
            {both.some((d) => d?.report?.stats?.agentic) ? (
              <div className="chart" role="img" aria-label="Time per phase of both runs">
                <div className="chart-title">
                  Time per phase: <RunTag which="A" /> {left.data && runTitle(left.data)} vs <RunTag which="B" /> {right.data && runTitle(right.data)}{" "}
                  <span className="better">(less is faster)</span>
                </div>
                <ResponsiveContainer width="100%" height={phaseData.length * 44 + 16}>
                  <BarChart data={phaseData} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 0 }} barCategoryGap="20%">
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="phase" width={110} tick={{ fill: "var(--text-2)", fontSize: 13 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v) => seconds(Number(v))} />
                    {(["A", "B"] as const).map((k, i) => (
                      <Bar key={k} dataKey={k} name={`${k}: ${(i ? right : left).data?.name || ""}`} fill={SERIES[i]} radius={[0, 3, 3, 0]} minPointSize={1} isAnimationActive={ANIMATE}>
                        <LabelList dataKey={k} position="right" formatter={(v: unknown) => (Number(v) ? seconds(Number(v)) : "0")} className="bar-label" />
                      </Bar>
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <Empty>Phases exist for agent-team runs only.</Empty>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
