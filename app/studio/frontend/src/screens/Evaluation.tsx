import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, ApiError, useApi, type Table } from "../api";
import { ANIMATE, Async, Badge, Card, DataTable, Empty, Tabs } from "../components/common";
import {
  auditBars,
  costBars,
  injectionBars,
  KINDS,
  kindBars,
  methodName,
  probeBars,
  records,
  reviewBars,
  scenarioBars,
  sources,
  watchBars,
  type Row,
} from "../state/evaluation";

type TabKey = "injection" | "ablations" | "audit" | "probes" | "manager" | "reviewer" | "watch";

const TABS: { key: TabKey; label: string }[] = [
  { key: "injection", label: "Injection benchmark" },
  { key: "ablations", label: "Ablations" },
  { key: "audit", label: "Diff audit" },
  { key: "probes", label: "Probe strength" },
  { key: "manager", label: "Manager scenarios" },
  { key: "reviewer", label: "LLM reviewer" },
  { key: "watch", label: "Watch" },
];

const AXIS = { fill: "var(--muted)", fontSize: 12 };
// the kinds in KINDS order; series-6 sits too close to series-3, so "other" takes series-7
const KIND_COLORS = [1, 2, 3, 4, 5, 7].map((n) => `var(--series-${n})`);
const TOOLTIP = { background: "var(--surface)", border: "1px solid var(--border)" };
const judged = (text = "LLM-judged") => <Badge tone="info">{text}</Badge>;

// A committed table; a missing one comes back empty, so the screen can say it is not built yet.
function useTable(name: string) {
  return useApi<Table>(`evaluation:${name}`, () =>
    api<Table>("/api/table", { root: "results", path: `summary/v2/${name}` }).catch((err) => {
      if (err instanceof ApiError && err.status === 404) return { columns: [], rows: [] };
      throw err;
    }),
  );
}

function Loaded({ name, children }: { name: string; children: (table: Table) => ReactNode }) {
  const res = useTable(name);
  return (
    <Async res={res} what={`Loading ${name}`} empty={(t) => (t.columns.length ? null : `${name} is not built yet (scripts/reproduce_tables.sh).`)}>
      {children}
    </Async>
  );
}

function Bars({
  data,
  x,
  series,
  stacked = false,
  percent = false,
  error,
  title,
}: {
  data: Row[];
  x: string;
  series: { key: string; name: string; color?: string }[];
  stacked?: boolean;
  percent?: boolean;
  error?: string;
  title: string;
}) {
  if (!data.length) return <Empty>Nothing to chart.</Empty>;
  const format = (v: unknown) => (percent ? `${Math.round(Number(v) * 100)}%` : String(v));
  // long or many labels are tilted so they never overlap
  const tilt = data.length > 6 || data.some((d) => String(d[x]).length > 14);
  return (
    <div className="chart" role="img" aria-label={title}>
      <div className="chart-title">{title}</div>
      <ResponsiveContainer width="100%" height={tilt ? 280 : 260}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: tilt ? 48 : 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={x} tick={AXIS} interval={0} angle={tilt ? -20 : 0} textAnchor={tilt ? "end" : "middle"} height={tilt ? 84 : 30} />
          <YAxis tick={AXIS} tickFormatter={format} domain={percent ? [0, 1] : [0, "auto"]} width={44} />
          <Tooltip contentStyle={TOOLTIP} formatter={(v) => format(v)} cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.name}
              stackId={stacked ? "one" : undefined}
              fill={s.color ?? `var(--series-${i + 1})`}
              stroke="var(--surface)"
              strokeWidth={stacked ? 2 : 0}
              maxBarSize={36}
              radius={stacked && i < series.length - 1 ? 0 : [4, 4, 0, 0]}
              isAnimationActive={ANIMATE}
            >
              {error && i === 0 && <ErrorBar dataKey={error} width={6} stroke="var(--text)" />}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Injection() {
  return (
    <>
      <Card title="Planted slop removed and traps removed, per method">
        <Loaded name="injection_seeds.csv">
          {(t) => {
            const bars = injectionBars(records(t));
            return (
              <div className="chart-pair">
                <Bars data={bars} x="method" series={[{ key: "share", name: "planted slop removed" }]} percent error="ci" title="Planted slop removed per run (mean, 95% CI)" />
                <Bars data={bars} x="method" series={[{ key: "traps", name: "traps removed" }]} title="Traps removed (each one changes behavior)" />
              </div>
            );
          }}
        </Loaded>
        <p className="muted">All seeds pooled, with a bootstrap CI over project and seed. The table has each seed.</p>
      </Card>
      <Card title="By seed and pooled">
        <Loaded name="injection_seeds.csv">{(t) => <DataTable table={t} label="injection_seeds.csv" maxHeight={320} />}</Loaded>
      </Card>
      <Card title="The team against the other methods, paired by project and seed">
        <Loaded name="injection_paired.csv">{(t) => <DataTable table={t} label="injection_paired.csv" />}</Loaded>
      </Card>
      <Card title="The extended framework rule, re-scored (as run and with the rule)">
        <Loaded name="inject_rule.csv">{(t) => <DataTable table={t} label="inject_rule.csv" />}</Loaded>
      </Card>
    </>
  );
}

function AblationCost({ rows }: { rows: Row[] }) {
  const sets = sources(rows, "set");
  const [set, setSet] = useState(sets.includes("injected") ? "injected" : sets[0]);
  const bars = costBars(rows, set);
  return (
    <>
      <div className="card-actions">
        <select value={set} onChange={(e) => setSet(e.target.value)} aria-label="Ablation set">
          {sets.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="chart-pair">
        <Bars data={bars} x="method" series={[{ key: "llm", name: "LLM requests" }]} title="LLM requests per run (mean)" />
        <Bars data={bars} x="method" series={[{ key: "minutes", name: "minutes" }]} title="Minutes per run (median)" />
      </div>
    </>
  );
}

function Ablations() {
  return (
    <>
      <Card title="Real projects: the team, no research squad, a single agent">
        <Loaded name="real_ablation.csv">{(t) => <DataTable table={t} label="real_ablation.csv" />}</Loaded>
        <p className="muted">Wrong edits count all tiers, with those confirmed by a test, check or rule in brackets; the debatable edits and the LLM reviewer's acceptance are LLM-judged. The table scrolls sideways for the UI check, requests and minutes.</p>
      </Card>
      <Card title="Ablations on the answer keys, SWE-bench, AIDev and the injected set">
        <Loaded name="ablations.csv">{(t) => <AblationCost rows={records(t)} />}</Loaded>
        <Loaded name="ablations.csv">{(t) => <DataTable table={t} label="ablations.csv" maxHeight={360} />}</Loaded>
      </Card>
    </>
  );
}

function AuditCharts({ audit, types }: { audit: Row[]; types: Row[] }) {
  const all = sources(audit);
  const [source, setSource] = useState(all.includes("injected") ? "injected" : all[0]);
  const shown = audit.filter((r) => r.source === source);
  return (
    <>
      <div className="card-actions">
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Target set">
          {all.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="chart-pair">
        <Bars
          data={auditBars(audit, source)}
          x="method"
          stacked
          series={[
            { key: "confirmed", name: "wrong, confirmed (test, UI check or rule)" },
            { key: "reading", name: "wrong, reading (LLM-judged)" },
          ]}
          title="Wrong edits per 100 kept code edits, by tier"
        />
        <Bars data={kindBars(types, source)} x="method" stacked series={KINDS.map((k, i) => ({ key: k, name: k, color: KIND_COLORS[i] }))} title="Wrong edits by kind (count)" />
      </div>
      <DataTable
        table={{
          columns: ["method", "kept code edits", "wrong (all tiers)", "confirmed", "reading (LLM-judged)", "debatable", "wrong rate [95% CI]", "missed by every check"],
          rows: shown.map((r) => [methodName(r.method), r.kept_code_edits, r.wrong, r.wrong_confirmed, r.wrong_reading, r.debatable, `${r.wrong_rate} [${r.ci_low}, ${r.ci_high}]`, r.missed_by_every_check]),
        }}
        label="diff_audit.csv"
      />
    </>
  );
}

function Audit() {
  return (
    <Card title={<>Diff audit: wrong edits by tier and kind {judged("reading tier: LLM-judged")}</>}>
      <p className="muted">
        An independent model flagged kept edits; each flag was then checked. Confirmed means a targeted test in the run's own environment, the UI check, or the injection key's or agent patch's rule; reading means the check is LLM-judged.
      </p>
      <Loaded name="diff_audit.csv">{(audit) => <Loaded name="diff_audit_types.csv">{(types) => <AuditCharts audit={records(audit)} types={records(types)} />}</Loaded>}</Loaded>
    </Card>
  );
}

function Probes() {
  return (
    <Card title="Probe strength: what the tests and the probes catch">
      <Loaded name="probe_strength.csv">
        {(t) => (
          <>
            <Bars
              data={probeBars(records(t))}
              x="label"
              stacked
              percent
              series={[
                { key: "tests", name: "caught by the tests" },
                { key: "probes", name: "caught only by the probes" },
              ]}
              title="Share of mutations and PatchDiff changes caught"
            />
            <DataTable table={t} label="probe_strength.csv" />
          </>
        )}
      </Loaded>
    </Card>
  );
}

function Manager() {
  return (
    <Card title="Manager scenarios: the LLM Manager and the rule-based one">
      <Loaded name="manager_scenarios.csv">
        {(t) => (
          <>
            <Bars
              data={scenarioBars(records(t))}
              x="scenario"
              percent
              series={[
                { key: "llm", name: "LLM Manager" },
                { key: "rules", name: "rule-based Manager" },
              ]}
              title="Runs where the Manager did what the scenario expects"
            />
            <DataTable table={t} label="manager_scenarios.csv" />
          </>
        )}
      </Loaded>
    </Card>
  );
}

function Reviewer() {
  return (
    <Card title={<>LLM-reviewer acceptance of the case studies' changes {judged()}</>}>
      <p className="muted">An independent model, blinded to the method, judged each change; no person has checked these verdicts.</p>
      <Loaded name="llm_review_acceptance.csv">
        {(t) => (
          <>
            <Bars data={reviewBars(records(t))} x="project" percent series={[{ key: "acceptance", name: "accepted" }]} title="Changes the LLM reviewer accepts, per project (LLM-judged)" />
            <DataTable table={t} label="llm_review_acceptance.csv" maxHeight={320} />
          </>
        )}
      </Loaded>
    </Card>
  );
}

function Watch() {
  return (
    <Card title="Watch: slop left behind and test runs spent, per sweep policy">
      <Loaded name="watch_replay.csv">
        {(t) => {
          const bars = watchBars(records(t));
          return (
            <>
              <div className="chart-pair">
                <Bars data={bars} x="policy" series={[{ key: "debt", name: "slop debt per commit" }]} title="Slop debt per commit (mean over repositories)" />
                <Bars data={bars} x="policy" series={[{ key: "tests", name: "test runs" }]} title="Test runs spent (mean over repositories)" />
              </div>
              <DataTable table={t} label="watch_replay.csv" maxHeight={280} />
            </>
          );
        }}
      </Loaded>
    </Card>
  );
}

export function Evaluation({ tab, onTab }: { tab: string; onTab: (tab: string) => void }) {
  const active = (TABS.find((t) => t.key === tab)?.key ?? "injection") as TabKey;
  const screens: Record<TabKey, ReactNode> = {
    injection: <Injection />,
    ablations: <Ablations />,
    audit: <Audit />,
    probes: <Probes />,
    manager: <Manager />,
    reviewer: <Reviewer />,
    watch: <Watch />,
  };
  return (
    <div className="screen">
      <header className="screen-head">
        <h2>Evaluation</h2>
        <span className="muted">The v2 results, read from the committed tables (results/summary/v2/).</span>
      </header>
      <Tabs tabs={TABS} value={active} onChange={onTab} />
      {screens[active]}
    </div>
  );
}
