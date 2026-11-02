import { useEffect } from "react";
import { CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, runHash, useApi, type Table } from "../api";
import { Async, Card, DataTable, Empty, Stat, Status } from "../components/common";
import { useRuns } from "./Runs";

interface Entry {
  t: string;
  commit: string;
  subject: string;
  new_commits: number;
  commits_since_clean: number;
  slop: { items: number; loc: number; share: number; by_category: Record<string, number> };
  new_items: number;
  decision: "clean" | "wait";
  reason: string;
  run: string | null;
  outcome: { verdict: string; applied: number; lines_removed: number; test_runs: number } | null;
  test_runs_used: number;
  budget_tests: number;
}

interface WatchLog {
  entries: Entry[];
  state: Record<string, any> | null;
  runs: string[];
}

function WatchView({ root, path, live }: { root: string; path: string; live: boolean }) {
  const res = useApi<WatchLog>(`watch:${root}/${path}`, () => api("/api/watch", { root, path }));
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(res.reload, 3000);
    return () => clearInterval(timer);
  }, [live, res.reload]);
  return (
    <Async res={res} what="Loading the watch log" empty={(w) => (w.entries.length ? null : "No polls logged yet.")}>
      {(w) => {
        const last = w.entries[w.entries.length - 1];
        const data = w.entries.map((e, i) => ({
          poll: i + 1,
          items: e.slop.items,
          share: Math.round(e.slop.share * 1000) / 10,
          clean: e.decision === "clean" ? e.slop.items : null,
          label: `${e.commit.slice(0, 8)} ${e.subject}`,
        }));
        return (
          <>
            <div className="stats-row">
              <Stat label="polls" value={w.entries.length} />
              <Stat label="cleans" value={w.entries.filter((e) => e.decision === "clean").length} />
              <Stat label="open slop items" value={last.slop.items} />
              <Stat label="slop share" value={`${(last.slop.share * 100).toFixed(1)}%`} />
              <Stat label="test runs used" value={`${last.test_runs_used} / ${last.budget_tests || "∞"}`} />
            </div>
            <Card title="Slop over time">
              <div className="chart">
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="poll" tick={{ fill: "var(--muted)", fontSize: 12 }} label={{ value: "poll", position: "insideBottomRight", offset: -4, fill: "var(--muted)" }} />
                    <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />
                    <Tooltip
                      contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
                      labelFormatter={(_, p) => {
                        const row = p?.[0]?.payload;
                        return row ? `${row.label} (slop ${row.share}% of the Python lines)` : "";
                      }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="items" name="open slop items" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 4 }} />
                    {data
                      .filter((d) => d.clean !== null)
                      .map((d) => (
                        <ReferenceLine
                          key={d.poll}
                          x={d.poll}
                          stroke="var(--series-3)"
                          strokeDasharray="4 3"
                          label={{ value: "clean", position: "insideTopRight", fill: "var(--text-2)", fontSize: 12 }}
                        />
                      ))}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Commit stream and decisions">
              <ol className="commits" reversed>
                {[...w.entries].reverse().map((e, i) => (
                  <li key={`${e.commit}-${i}`} className={`commit decision-${e.decision}`}>
                    <code>{e.commit.slice(0, 10)}</code> <span className="subject">{e.subject}</span>{" "}
                    <span className="muted small">
                      {e.t} · {e.new_commits} new commit(s) · {e.slop.items} slop items ({e.new_items} new)
                    </span>
                    <div>
                      <Status value={e.decision} /> <span className="reason">{e.reason}</span>
                    </div>
                    {e.run && (
                      <div className="small">
                        {e.run}: {e.outcome ? <Status value={e.outcome.verdict} /> : "running"}
                        {e.outcome && ` · ${e.outcome.applied} applied, ${e.outcome.lines_removed} lines removed, ${e.outcome.test_runs} test runs`}{" "}
                        {w.runs.includes(e.run) && <a href={runHash({ root, path: `${path}/${e.run}` })}>replay</a>}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </Card>
          </>
        );
      }}
    </Async>
  );
}

export function Watch({ root, path, onPick }: { root: string; path: string; onPick: (root: string, path: string) => void }) {
  const runs = useRuns();
  const replay = useApi<{ table: Table | null }>("watch-replay", () => api("/api/watch-replay"));
  return (
    <div className="screen">
      <header className="screen-head">
        <h2>Watch</h2>
        <span className="muted">
          `cleansweep watch` follows a repository's commits and decides when to clean. <a href="#/launch">Start a watch</a>
        </span>
      </header>
      <Async res={runs} what="Finding watch folders">
        {(rows) => {
          const folders = rows.filter((r) => r.kind === "watch");
          return folders.length ? (
            <div className="filters">
              <label>
                Watch folder{" "}
                <select
                  value={root && path ? `${root}:${path}` : ""}
                  onChange={(e) => {
                    const [r, ...p] = e.target.value.split(":");
                    onPick(r, p.join(":"));
                  }}
                  aria-label="Watch folder"
                >
                  <option value="">pick one</option>
                  {folders.map((f) => (
                    <option key={`${f.root}:${f.path}`} value={`${f.root}:${f.path}`}>
                      {f.name} ({f.root}/{f.path})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <Empty>No watch folders yet.</Empty>
          );
        }}
      </Async>
      {root && path && <WatchView root={root} path={path} live={(runs.data || []).some((r) => r.root === root && r.path === path && r.live)} />}
      <Card title="Simulated watch over repository histories (results/summary/v2/watch_replay.csv)">
        <Async res={replay}>{(d) => (d.table ? <DataTable table={d.table} label="Simulated watch" /> : <Empty>The simulated watch table is not there yet.</Empty>)}</Async>
      </Card>
    </div>
  );
}
