// The Phase 1 dashboard's pages (saved reports, Scheduler, Baselines, Data, Guard) with the same data.
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, useApi, type ReportView, type SavedReport, type Table } from "../api";
import { AXIS, SeriesKey, TOOLTIP } from "../components/Charts";
import { CodeBlock, DiffView } from "../components/Code";
import { ANIMATE, Async, Card, DataTable, Empty, PageHeader, StatsRow, Status, Tabs } from "../components/common";
import { isIsoDate, shortDate } from "../state/labels";
import { Figure } from "./Results";

interface Scheduler {
  replay: Table | null;
  repos_count?: number;
  excluded?: number;
  means?: Table;
  tradeoff?: Table | null;
  figure?: string | null;
  repos?: string[];
  repo?: string;
  policies?: string[];
  curves?: Table | null;
}

function records(t: Table | null | undefined): Record<string, any>[] {
  if (!t) return [];
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])));
}

function reposLabel(repos: number, excluded = 0) {
  return excluded ? `${repos} of ${repos + excluded} runnable repos (${excluded} excluded)` : `${repos} runnable repos`;
}

export function SchedulerScreen() {
  const [repo, setRepo] = useState<string | undefined>(undefined);
  const [policy, setPolicy] = useState<string | undefined>(undefined);
  const res = useApi<Scheduler>(`scheduler:${repo || ""}`, () => api("/api/parity/scheduler", { repo }));
  return (
    <div className="screen">
      <PageHeader
        title="Scheduler replay"
        description="Phase 1: when to sweep a repository, replayed over its real commit history."
        help="Each policy sweeps at different moments; slop debt is the open slop summed over commits. Lower debt for fewer test runs is better."
      />
      <Async
        res={res}
        what="Loading the replay"
        empty={(d) => (d.replay ? null : "No replay yet; scripts/experiments/v1/exp_replay.py writes it.")}
        emptyAction={{ label: "Check again", onClick: res.reload }}
      >
        {(d) => {
          const chosen = policy && d.policies?.includes(policy) ? policy : d.policies?.[0];
          const curves = records(d.curves);
          const byIndex = new Map<number, Record<string, any>>();
          for (const c of curves) {
            if (c.policy !== "none" && c.policy !== chosen) continue;
            const row = byIndex.get(c.index) || { index: c.index };
            row[c.policy === "none" ? "never" : "policy"] = c.open_slop;
            if (c.policy !== "none" && c.swept) row.sweep = c.open_slop;
            byIndex.set(c.index, row);
          }
          const series = [...byIndex.values()].sort((a, b) => a.index - b.index);
          return (
            <>
              <p className="muted small">
                Static detectors only, measured at up to 40 commits of each repository's last 300 first-parent commits. Slop debt = open slop
                items summed over commits; a sweep removes all open slop. Resurrection = removed code that a later commit started using.
              </p>
              <Card title={`Policies over ${reposLabel(d.repos_count || 0, d.excluded)} (means)`}>
                <DataTable table={d.means} label="Policy means" />
              </Card>
              {d.tradeoff && (
                <Card title="Trade-off: test runs vs. slop-debt reduction">
                  <p className="muted small">
                    Per repository, reduction = 1 - slop debt / slop debt when never sweeping; means and 95% bootstrap CIs across repositories.
                  </p>
                  <DataTable table={d.tradeoff} label="Trade-off" />
                  <Figure path={d.figure} caption="scheduler_tradeoff.png" />
                </Card>
              )}
              <Card
                title={d.repo}
                actions={
                  <>
                    <select value={d.repo} onChange={(e) => setRepo(e.target.value)} aria-label="Repository">
                      {d.repos?.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                    <select value={chosen} onChange={(e) => setPolicy(e.target.value)} aria-label="Policy">
                      {d.policies?.map((p) => (
                        <option key={p}>{p}</option>
                      ))}
                    </select>
                  </>
                }
              >
                <DataTable table={d.replay} label="Repository replay" />
                {series.length ? (
                  <div className="chart">
                    <SeriesKey
                      series={[
                        { name: "never sweep", color: "var(--series-2)" },
                        { name: `${chosen} (dots: a sweep)`, color: "var(--series-1)" },
                      ]}
                    />
                    <ResponsiveContainer width="100%" height={300}>
                      <ComposedChart data={series} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                        <XAxis dataKey="index" tick={AXIS} label={{ value: "commit (oldest to newest)", position: "insideBottom", offset: -8, fill: "var(--muted)" }} />
                        <YAxis tick={AXIS} label={{ value: "open slop items", angle: -90, position: "insideLeft", fill: "var(--muted)" }} />
                        <Tooltip contentStyle={TOOLTIP} />
                        <Line type="monotone" dataKey="never" name="never sweep" stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={ANIMATE} />
                        <Line type="monotone" dataKey="policy" name={chosen} stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={ANIMATE} />
                        <Line dataKey="sweep" name="sweep" stroke="var(--series-1)" strokeWidth={0} dot={{ r: 4, fill: "var(--series-1)", strokeWidth: 0 }} legendType="circle" isAnimationActive={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <Empty>No curves for this repository.</Empty>
                )}
              </Card>
            </>
          );
        }}
      </Async>
    </div>
  );
}

export function BaselinesScreen() {
  const res = useApi<{ main: Table | null; paired: Table | null; ablation: Table | null; figure: string | null }>("baselines", () =>
    api("/api/parity/baselines"),
  );
  const [sets, setSets] = useState<string[] | null>(null);
  return (
    <div className="screen">
      <PageHeader
        title="Baselines and ablations"
        description="Phase 1: the sweep against the baselines, and what each of its parts adds."
        help="Means per target with 95% bootstrap intervals; pick the target sets to include. The paired tests compare each method with the sweep."
      />
      <Async
        res={res}
        what="Loading the tables"
        empty={(d) => (d.main ? null : "No results yet; exp_collect.py and exp_tables.py write them.")}
        emptyAction={{ label: "Check again", onClick: res.reload }}
      >
        {(d) => {
          const col = d.main!.columns.indexOf("target set");
          const all = [...new Set(d.main!.rows.map((r) => String(r[col])))];
          const chosen = sets || all;
          const inSets = (t: Table | null) => (row: unknown[]) => !t || t.columns.indexOf("target set") < 0 || chosen.includes(String(row[t.columns.indexOf("target set")]));
          return (
            <>
              <p className="muted small">
                Mean per target and 95% bootstrap CI (2,000 resamples). Answer keys pool the toy repo and the demo app (one target each). Hidden
                changed = the share of targets whose hidden checks changed. Invalid output counts one-shot replies that could not be applied;
                they are left out of the means.
              </p>
              <div className="filters">
                Target sets:
                {all.map((s) => (
                  <label key={s} className="check">
                    <input
                      type="checkbox"
                      checked={chosen.includes(s)}
                      onChange={(e) => setSets(e.target.checked ? [...chosen, s] : chosen.filter((x) => x !== s))}
                    />{" "}
                    {s}
                  </label>
                ))}
              </div>
              <Card title="Main table">
                <DataTable table={d.main} filter={inSets(d.main)} label="Main table" />
                <Figure path={d.figure} caption="Lines removed per target (mean, 95% CI)" />
              </Card>
              {d.paired && (
                <Card title="Paired tests against cleansweep in gatekeeper mode">
                  <p className="muted small">Same targets for both methods. McNemar (exact) on hidden changes, Wilcoxon signed-rank on lines removed.</p>
                  <DataTable table={d.paired} filter={inSets(d.paired)} label="Paired tests" />
                </Card>
              )}
              {d.ablation && (
                <Card title="Ablations: what each part adds">
                  <DataTable table={d.ablation} filter={inSets(d.ablation)} label="Ablations" />
                </Card>
              )}
            </>
          );
        }}
      </Async>
    </div>
  );
}

interface DataPage {
  counts: Table | null;
  tiers: Table | null;
  funnel: Table | null;
  drop_reasons: Table | null;
  taxonomy: Table | null;
  rules: Table | null;
  detection: Table | null;
}

export function DataScreen() {
  const res = useApi<DataPage>("data", () => api("/api/parity/data"));
  const [level, setLevel] = useState<"category" | "cluster">("category");
  return (
    <div className="screen">
      <PageHeader
        title="Data"
        description="Phase 1: the datasets behind the experiments (SWE-bench Verified, PatchDiff and AIDev)."
        help="How many items each dataset has, how the AIDev repositories were selected, and which removal requests the detectors catch."
      />
      <Async res={res} what="Loading the data summaries">
        {(d) => {
          const funnel = records(d.funnel);
          const levelCol = d.detection ? d.detection.columns.indexOf("level") : -1;
          return (
            <>
              <h3>SWE-bench Verified and PatchDiff</h3>
              {!d.counts && !d.tiers && <Empty>Run python scripts/data/data_summary.py to write the counts.</Empty>}
              <div className="grid two">
                {d.counts && (
                  <Card title="Counts">
                    <DataTable table={d.counts} label="Counts" />
                  </Card>
                )}
                {d.tiers && (
                  <Card title="Tiers">
                    <p className="muted small">Differ = PatchDiff says the patch behaves differently from the developer's fix.</p>
                    <DataTable table={d.tiers} label="Tiers" />
                  </Card>
                )}
              </div>
              <h3>AIDev</h3>
              {funnel.length > 0 && (
                <Card title="Selection funnel">
                  <div className="chart">
                    <ResponsiveContainer width="100%" height={Math.max(200, funnel.length * 30 + 40)}>
                      <BarChart data={funnel} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
                        <XAxis
                          type="number"
                          scale="log"
                          domain={[1, 100000]}
                          ticks={[1, 10, 100, 1000, 10000, 100000]}
                          allowDataOverflow
                          tick={{ fill: "var(--muted)", fontSize: 12 }}
                        />
                        <YAxis type="category" dataKey="stage" width={220} tick={{ fill: "var(--muted)", fontSize: 12 }} />
                        <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                        <Bar dataKey="count" name="repositories (log scale)" fill="var(--series-1)" label={{ position: "right", fill: "var(--text)", fontSize: 12 }} isAnimationActive={ANIMATE} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  {funnel
                    .filter((f) => f.note)
                    .map((f) => (
                      <p key={f.stage} className="muted small">
                        {f.stage}: {f.note}
                      </p>
                    ))}
                  <h4>Why candidates were dropped</h4>
                  <DataTable table={d.drop_reasons} label="Drop reasons" />
                </Card>
              )}
              {d.taxonomy && (
                <Card title="Kinds of removal requests (taxonomy clusters)">
                  <p className="muted small">TF-IDF on the request text (without @-mentions), KMeans with k by silhouette.</p>
                  <DataTable table={d.taxonomy} label="Taxonomy" />
                </Card>
              )}
              {d.rules && (
                <Card title="Top association rules (by lift)">
                  <DataTable table={d.rules} label="Association rules" />
                </Card>
              )}
              {d.detection && (
                <Card
                  title="Reviewer detection by kind of request"
                  actions={<Tabs tabs={[{ key: "category", label: "category" }, { key: "cluster", label: "cluster" }]} value={level} onChange={setLevel} />}
                >
                  <p className="muted small">
                    Requested units = units reviewers asked agents to remove; flagged = what the static detectors report in the same commented
                    files. Flagged as = the detector categories that do flag requested units.
                  </p>
                  <DataTable table={d.detection} filter={(row) => row[levelCol] === level} label="Detection by category" />
                </Card>
              )}
              {!funnel.length && !d.taxonomy && !d.rules && !d.detection && <Empty>No AIDev summaries yet.</Empty>}
            </>
          );
        }}
      </Async>
    </div>
  );
}

export function GuardScreen() {
  const res = useApi<{ strength: Table | null; false_alarms: Table | null; figure: string | null }>("guard", () => api("/api/parity/guard"));
  return (
    <div className="screen">
      <PageHeader
        title="Guard strength"
        description="Phase 1: how many deliberate behavior changes the Guard's tests and probes catch, and how often it raises a false alarm."
        help="Higher catch rates are better; false alarms should be zero. Caught only by the probes means the tests alone would have missed it."
      />
      <Async
        res={res}
        what="Loading the measurement"
        empty={(d) => (d.strength ? null : "No measurement yet; scripts/experiments/v1/exp_guard_strength.py writes it.")}
        emptyAction={{ label: "Check again", onClick: res.reload }}
      >
        {(d) => (
          <>
            <p className="muted small">
              Mutants: one small change per function (flip a comparison, swap + and -, add 1 to an int, swap and/or, return None); caught if the
              Guard's verify fails. PatchDiff recall: the agent patch against the developer's fix, for patches PatchDiff says behave differently.
              Probe mode: direct runs the probes as a script; runner runs them inside the project's own test command (Django settings,
              conftest.py).
            </p>
            <Card title="Caught by the tests vs. only by the probes">
              <DataTable table={d.strength} label="Guard strength" />
              <Figure path={d.figure} caption="Share of mutants caught, by target set and probe mode" />
            </Card>
            <Card title="False alarms">
              <p className="muted small">verify on two identical copies, probing up to 10 touched functions although nothing changed: any rejection is a false alarm.</p>
              <DataTable table={d.false_alarms} label="False alarms" />
            </Card>
          </>
        )}
      </Async>
    </div>
  );
}

export function restoreCommand(evidence: string[], unit: string): string | null {
  const line = evidence.find((e) => e.startsWith("quarantined at "));
  return line ? `cp '${line.slice("quarantined at ".length)}' '${unit}'` : null;
}

function Report({ root, path }: { root: string; path: string }) {
  const res = useApi<ReportView>(`report:${root}/${path}`, () => api("/api/report", { root, path }));
  return (
    <Async res={res} what="Loading the report">
      {(r) => {
        const units = Object.fromEntries(r.items.map((i) => [i.item_id, i]));
        const status = Object.fromEntries(r.results.map((x) => [x.item_id, x.status]));
        const cleaned = r.results.filter((x) => x.status === "kept" || x.status === "repaired").length;
        const plan: Table = {
          columns: ["status", "lane", "category", "unit", "action", "safe_score", "reason"],
          rows: r.items.map((i) => [status[i.item_id] || "-", i.lane, i.category, i.unit, i.action, i.safe_score, i.reason]),
        };
        const verdicts = r.results.filter((x) => x.status !== "skipped" && units[x.item_id]);
        return (
          <>
            <p className="muted small">
              {r.repo_id} · method {r.method} · started <span title={r.started_at}>{isIsoDate(r.started_at) ? shortDate(r.started_at) : r.started_at}</span>
            </p>
            <StatsRow
              label="Report numbers"
              items={[
                {
                  label: `Slop cleaned (items), ${Math.max(r.items.length - cleaned, 0)} still open`,
                  value: `${cleaned} / ${r.items.length}`,
                  lead: true,
                  share: cleaned / Math.max(r.items.length, 1),
                },
                { label: "Items found", value: r.stats.items_total ?? r.items.length },
                { label: "Kept", value: (r.stats.items_kept || 0) + (r.stats.items_repaired || 0) },
                { label: "Rolled back", value: r.stats.items_rolled_back || 0 },
                { label: "Lines removed", value: r.stats.lines_removed || 0 },
                { label: "Test runs", value: r.stats.test_runs || 0 },
              ]}
            />
            <Card title="Cleanup plan">
              <DataTable table={plan} label="Cleanup plan" />
            </Card>
            <Card title="Guard verdicts">
              {verdicts.length ? (
                verdicts.map((x) => {
                  const item = units[x.item_id];
                  const restore = restoreCommand(item.evidence || [], item.unit);
                  return (
                    <details key={x.item_id}>
                      <summary>
                        <Status value={x.status} /> {item.category} · {item.unit}
                      </summary>
                      <p>{item.reason}</p>
                      {x.tests && (
                        <p className="small">
                          tests: {x.tests.passed} passed, {x.tests.failed} failed
                        </p>
                      )}
                      {x.notes && <pre className="log" tabIndex={0}>{x.notes}</pre>}
                      {x.diff && <DiffView text={x.diff} />}
                      {restore && <CodeBlock code={restore} language="bash" />}
                    </details>
                  );
                })
              ) : (
                <Empty>The Guard checked nothing in this report.</Empty>
              )}
            </Card>
          </>
        );
      }}
    </Async>
  );
}

export function ReportsScreen({ root, path, onPick }: { root: string; path: string; onPick: (root: string, path: string) => void }) {
  const res = useApi<SavedReport[]>("reports", () => api("/api/reports"));
  return (
    <div className="screen">
      <PageHeader
        title="Saved reports"
        description="Every Phase 1 sweep report, newest first."
        help="Reports saved under results/, the runs folder and demo/replay/: a sweep's numbers, its plan, and each Guard verdict with its diff; a quarantined file comes with the command that restores it."
      />
      <Async
        res={res}
        what="Finding saved reports"
        empty={(rows) => (rows.length ? null : "No saved reports yet; cleansweep sweep --out saves one.")}
        emptyAction={{ label: "Open Runs", href: "#/runs" }}
      >
        {(rows) => {
          const chosen = rows.find((r) => r.root === root && r.path === path) || rows[0];
          return (
            <>
              <div className="filters">
                <label>
                  Sweep report{" "}
                  <select
                    value={`${chosen.root}:${chosen.path}`}
                    onChange={(e) => {
                      const [r, ...p] = e.target.value.split(":");
                      onPick(r, p.join(":"));
                    }}
                    aria-label="Sweep report"
                  >
                    {rows.map((r) => (
                      <option key={`${r.root}:${r.path}`} value={`${r.root}:${r.path}`}>
                        {r.root}/{r.path} ({r.method})
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <Report key={`${chosen.root}:${chosen.path}`} root={chosen.root} path={chosen.path} />
            </>
          );
        }}
      </Async>
    </div>
  );
}

// The Phase 1 dashboard's pages, one entry in the sidebar.
export const ARCHIVE: [string, string, string][] = [
  ["reports", "Saved reports", "Every sweep report: its numbers, plan and Guard verdicts with diffs."],
  ["sweeps", "Live sweep and replay", "The Phase 1 sweeps: stages, the Reviewer's plan, Guard checks and the answer-key score."],
  ["scheduler", "Scheduler", "When to sweep a repository, replayed over its real commit history."],
  ["baselines", "Baselines", "The sweep against the baselines, and what each of its parts adds."],
  ["data", "Data", "The datasets behind the experiments: SWE-bench Verified, PatchDiff and AIDev."],
  ["guard", "Guard", "How many deliberate behavior changes the Guard catches, and its false alarms."],
];

export function ArchiveScreen() {
  return (
    <div className="screen">
      <PageHeader
        title="Phase 1 archive"
        description="The Phase 1 sweep's screens, kept as they were for its results."
        help="Phase 1 was a fixed pipeline (detect, judge, batch, guard); the agent team of Phase 2 replaced it. These pages show its runs and tables."
      />
      <div className="archive">
        {ARCHIVE.map(([key, label, text]) => (
          <a key={key} className="archive-card" href={`#/${key}`}>
            <b>{label}</b>
            <span>{text}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
