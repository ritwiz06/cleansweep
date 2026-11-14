import { useEffect } from "react";
import { CartesianGrid, ComposedChart, LabelList, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, runHash, useApi, type Table } from "../api";
import { AXIS, SeriesKey, TOOLTIP } from "../components/Charts";
import { ANIMATE, Async, Card, DataTable, Empty, PageHeader, ShowMore, Status } from "../components/common";
import { records } from "../state/evaluation";
import { fileTitle } from "../state/names";
import { watchTakeaway } from "../state/takeaways";
import { isIsoDate, plural, shortDate } from "../state/labels";
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

// Under this many polls a line says little: the polls are a small table instead.
const FEW_POLLS = 5;

interface Point {
  poll: number;
  items: number;
  share: number;
  clean: number | null;
  label: string;
}

function PollTable({ entries }: { entries: Entry[] }) {
  return (
    <div className="table-wrap" tabIndex={0}>
      <table className="data" aria-label="Polls">
        <thead>
          <tr>
            <th className="num">Poll</th>
            <th>Commit</th>
            <th className="num">Open slop items</th>
            <th className="num">Slop share</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={`${e.commit}-${i}`}>
              <td className="num">{i + 1}</td>
              <td className="ident">
                <code>{e.commit.slice(0, 10)}</code> {e.subject}
              </td>
              <td className="num">{e.slop.items}</td>
              <td className="num">{(e.slop.share * 100).toFixed(1)}%</td>
              <td>
                <Status value={e.decision} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SlopChart({ data }: { data: Point[] }) {
  return (
    <div className="chart">
      <SeriesKey
        series={[
          { name: "Open slop items", color: "var(--series-1)" },
          { name: "A clean", color: "var(--series-3)", dashed: true },
        ]}
      />
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 20, right: 32, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="poll" tick={AXIS} padding={{ left: 24, right: 24 }} label={{ value: "poll", position: "insideBottomRight", offset: -4, fill: "var(--muted)" }} />
          <YAxis allowDecimals={false} tick={AXIS} />
          <Tooltip
            contentStyle={TOOLTIP}
            labelFormatter={(_, p) => {
              const row = p?.[0]?.payload;
              return row ? `${row.label} (slop ${row.share}% of the Python lines)` : "";
            }}
          />
          <Line type="stepAfter" dataKey="items" name="open slop items" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 4 }} isAnimationActive={ANIMATE}>
            <LabelList dataKey="items" position="top" offset={6} className="bar-label" />
          </Line>
          {data
            .filter((d) => d.clean !== null)
            .map((d) => (
              <ReferenceLine key={d.poll} x={d.poll} stroke="var(--series-3)" strokeDasharray="4 3" label={{ value: "clean", position: "insideBottomLeft", fill: "var(--text-2)", fontSize: 12 }} />
            ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// A watch folder in one sentence: how often it cleaned, the slop now, and the test runs used.
function watchSentence(entries: Entry[]): string {
  const last = entries[entries.length - 1];
  const cleans = entries.filter((e) => e.decision === "clean").length;
  const now = `slop is now ${(last.slop.share * 100).toFixed(1)}% of the Python lines`;
  const budget = last.budget_tests ? ` of ${last.budget_tests}` : "";
  return `Watch cleaned ${plural(cleans, "time")} in ${plural(entries.length, "poll")}; ${now}, with ${last.test_runs_used}${budget} test runs used.`;
}

// "raw/watch_demo/watch" -> "Watch demo": the folder's own name, not its path.
function folderTitle(path: string): string {
  return fileTitle(path.split("/").filter((s) => s && s !== "raw" && s !== "watch").pop() || path);
}

function WatchView({ root, path, live }: { root: string; path: string; live: boolean }) {
  const res = useApi<WatchLog>(`watch:${root}/${path}`, () => api("/api/watch", { root, path }));
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(res.reload, 3000);
    return () => clearInterval(timer);
  }, [live, res.reload]);
  return (
    <Async res={res} what="Loading the watch log" empty={(w) => (w.entries.length ? null : "No polls logged yet.")} emptyAction={{ label: "Check again", onClick: res.reload }}>
      {(w) => {
        const data = w.entries.map((e, i) => ({
          poll: i + 1,
          items: e.slop.items,
          share: Math.round(e.slop.share * 1000) / 10,
          clean: e.decision === "clean" ? e.slop.items : null,
          label: `${e.commit.slice(0, 8)} ${e.subject}`,
        }));
        return (
          <Card title="Slop over time">
            <p className="takeaway">{watchSentence(w.entries)}</p>
            {data.length < FEW_POLLS ? <PollTable entries={w.entries} /> : <SlopChart data={data} />}
            <ShowMore label="Show each poll's reason">
              <ol className="commits" reversed>
                {[...w.entries].reverse().map((e, i) => (
                  <li key={`${e.commit}-${i}`} className={`commit decision-${e.decision}`}>
                    <code>{e.commit.slice(0, 10)}</code> <span className="subject">{e.subject}</span>{" "}
                    <span className="muted small">
                      <span title={e.t}>{isIsoDate(e.t) ? shortDate(e.t) : e.t}</span> · {plural(e.new_commits, "new commit")} ·{" "}
                      {plural(e.slop.items, "slop item")} ({e.new_items} new)
                    </span>
                    <div>
                      <Status value={e.decision} /> <span className="reason">{e.reason}</span>
                    </div>
                    {e.run && (
                      <div className="small">
                        {e.run}: {e.outcome ? <Status value={e.outcome.verdict} /> : "running"}
                        {e.outcome &&
                          ` · ${e.outcome.applied} applied, ${plural(e.outcome.lines_removed, "line")} removed, ${plural(e.outcome.test_runs, "test run")}`}{" "}
                        {w.runs.includes(e.run) && <a href={runHash({ root, path: `${path}/${e.run}` })}>replay</a>}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </ShowMore>
          </Card>
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
      <PageHeader
        title="Watch"
        description="Watch mode follows a repository's commits and decides when a clean is worth its test runs."
        help="Each poll of cleansweep watch measures the open slop and decides: clean now, or wait (with the reason). Below, the simulated watch over recorded histories (results/summary/v2/watch_replay.csv)."
        actions={
          <a className="button" href="#/launch">
            Start a watch
          </a>
        }
      />
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
                    <option key={`${f.root}:${f.path}`} value={`${f.root}:${f.path}`} title={f.path}>
                      {folderTitle(f.path)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <Empty action={{ label: "Start a watch", href: "#/launch" }}>No watch folders yet.</Empty>
          );
        }}
      </Async>
      {root && path && <WatchView root={root} path={path} live={(runs.data || []).some((r) => r.root === root && r.path === path && r.live)} />}
      <Card title="Simulated watch over repository histories">
        <Async res={replay}>
          {(d) =>
            d.table ? (
              <>
                <p className="takeaway">{watchTakeaway(records(d.table))}</p>
                <ShowMore label="Show the table">
                  <DataTable table={d.table} label="Simulated watch" />
                </ShowMore>
              </>
            ) : (
              <Empty>The simulated watch table is not there yet.</Empty>
            )
          }
        </Async>
      </Card>
    </div>
  );
}
