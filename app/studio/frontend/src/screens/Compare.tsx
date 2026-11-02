import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, runHash, useApi, type RunDetail, type RunRow } from "../api";
import { Async, Card, Empty, Status, seconds } from "../components/common";
import { PHASES } from "../state/fold";
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
    time: s.wall_seconds !== undefined ? seconds(s.wall_seconds) : null,
    "packages kept": pk.length ? pk.filter((p) => p.status === "kept").length : null,
    "packages rolled back": pk.length ? pk.filter((p) => p.status === "rolled_back").length : null,
    "step backs": a.back_steps ? Object.values(a.back_steps as Record<string, number>).reduce((x, y) => x + y, 0) : null,
    "verdicts safe / suggest / drop": a.decisions ? `${a.decisions.safe} / ${a.decisions.suggest} / ${a.decisions.drop}` : null,
    lessons: a.lessons ? a.lessons.length : null,
  };
}

function Picker({ label, value, runs, onChange }: { label: string; value: string; runs: RunRow[]; onChange: (v: string) => void }) {
  return (
    <label>
      {label}{" "}
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        <option value="">pick a run</option>
        {runs.map((r) => (
          <option key={key(r)} value={key(r)}>
            {r.name} ({r.kind}, {r.root})
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
    phase: p.replace("_", " "),
    A: left.data?.report?.stats?.agentic?.phase_seconds?.[p] ?? 0,
    B: right.data?.report?.stats?.agentic?.phase_seconds?.[p] ?? 0,
  }));
  return (
    <div className="screen">
      <header className="screen-head">
        <h2>Compare two runs</h2>
      </header>
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
        <Empty>Pick two runs to see them side by side.</Empty>
      ) : (
        <>
          <Card title="Side by side">
            <Async res={left}>
              {() => (
                <Async res={right}>
                  {() => {
                    const rows = both.map((d) => (d ? numbers(d) : {}));
                    return (
                      <table className="data compare" aria-label="Comparison">
                        <thead>
                          <tr>
                            <th />
                            {both.map((d, i) => (
                              <th key={i}>
                                {i ? "B" : "A"}: {d?.name} {d && <a href={runHash(d)}>replay</a>}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {Object.keys(rows[0]).map((k) => (
                            <tr key={k}>
                              <th>{k}</th>
                              {rows.map((r, i) => (
                                <td key={i}>{k === "result" ? <Status value={r[k] as string} /> : (r[k] ?? "-")}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    );
                  }}
                </Async>
              )}
            </Async>
          </Card>
          <Card title="Time per phase (seconds)">
            {both.some((d) => d?.report?.stats?.agentic) ? (
              <div className="chart">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={phaseData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="phase" tick={{ fill: "var(--muted)", fontSize: 12 }} />
                    <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                    <Legend />
                    <Bar dataKey="A" name={`A: ${left.data?.name || ""}`} fill={SERIES[0]} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="B" name={`B: ${right.data?.name || ""}`} fill={SERIES[1]} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <Empty>Phases exist for agent-team (v2) runs only.</Empty>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
