import { useContext, useEffect, useState, type ReactNode } from "react";
import { Bar, BarChart, Cell, ErrorBar, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, ApiError, useApi, type Table } from "../api";
import { SeriesKey, TOOLTIP, nameOf, rowNamed, stackTotal, type LabelBox } from "../components/Charts";
import { ANIMATE, Async, Badge, Card, DataTable, Empty, PageHeader, Presenting, Tabs } from "../components/common";
import { formatNumber } from "../state/labels";
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
  v3RecallBars,
  watchBars,
  type Row,
} from "../state/evaluation";

type TabKey =
  | "injection"
  | "ablations"
  | "audit"
  | "probes"
  | "manager"
  | "reviewer"
  | "watch"
  | "v3-hypotheses"
  | "v3-injection"
  | "v3-real"
  | "v3-audit"
  | "v3-autonomy";

type Phase = "Phase 2" | "Phase 3";

const TABS: { key: TabKey; label: string; phase: Phase }[] = [
  { key: "injection", label: "Injection benchmark", phase: "Phase 2" },
  { key: "ablations", label: "Ablations", phase: "Phase 2" },
  { key: "audit", label: "Diff audit", phase: "Phase 2" },
  { key: "probes", label: "Probe strength", phase: "Phase 2" },
  { key: "manager", label: "Manager scenarios", phase: "Phase 2" },
  { key: "reviewer", label: "LLM reviewer", phase: "Phase 2" },
  { key: "watch", label: "Watch", phase: "Phase 2" },
  { key: "v3-hypotheses", label: "Hypotheses", phase: "Phase 3" },
  { key: "v3-injection", label: "Injection", phase: "Phase 3" },
  { key: "v3-real", label: "Real projects", phase: "Phase 3" },
  { key: "v3-audit", label: "Audit", phase: "Phase 3" },
  { key: "v3-autonomy", label: "Autonomy and cost", phase: "Phase 3" },
];
const PHASES: Phase[] = ["Phase 2", "Phase 3"];

// tables show the methods by the same names as the charts
const NAMES = { method: methodName };

// the kinds in KINDS order; series-6 sits too close to series-3, so "other" takes series-7
const KIND_COLORS = [1, 2, 3, 4, 5, 7].map((n) => `var(--series-${n})`);
const judged = (text = "LLM-judged") => <Badge tone="info">{text}</Badge>;

// A committed table (v2's or v3's); a missing one comes back empty, so the screen can say it is
// not built yet.
function useTable(name: string, version = "v2") {
  return useApi<Table>(`evaluation:${version}:${name}`, () =>
    api<Table>("/api/table", { root: "results", path: `summary/${version}/${name}` }).catch((err) => {
      if (err instanceof ApiError && err.status === 404) return { columns: [], rows: [] };
      throw err;
    }),
  );
}

function Loaded({ name, version, children }: { name: string; version?: string; children: (table: Table) => ReactNode }) {
  const res = useTable(name, version);
  return (
    <Async
      res={res}
      what={`Loading ${name}`}
      empty={(t) => (t.columns.length ? null : `${name} is not built yet; scripts/reproduce_tables.sh builds it.`)}
      emptyAction={{ label: "Check again", onClick: res.reload }}
    >
      {children}
    </Async>
  );
}

// The method every chart is about: drawn in the accent, the others in a quiet grey.
const FOCUS = "team";

// A bar's value just past its end, or past the end of its interval when it has one (the label's
// value is the row's name: valueAccessor={nameOf(name)}).
function valueAtEnd(rows: Row[], name: string, key: string, format: (v: number) => string, error?: string) {
  return function ValueLabel({ x, y, width, height, value: label }: LabelBox) {
    const row = rowNamed(rows, name, label);
    if (!row) return null;
    const value = Number(row[key]) || 0;
    const [bx, by, bw, bh] = [x, y, width, height].map(Number);
    const up = error ? Number((row[error] as number[])?.[1]) || 0 : 0;
    const whisker = value > 0 ? (bw / value) * up : 0;
    return (
      <text x={bx + bw + whisker + 6} y={by + bh / 2} dy={4} className="bar-label">
        {format(value)}
      </text>
    );
  };
}

// A category name on the left of its bar, left-aligned; the focus method in bold.
function nameTick(width: number) {
  return function NameTick({ x, y, payload }: { x?: number | string; y?: number | string; payload?: { value: string } }) {
    const name = payload?.value ?? "";
    return (
      <text x={Number(x) - width + 14} y={Number(y)} dy={4} textAnchor="start" className={name === FOCUS ? "bar-name focus" : "bar-name"}>
        {name}
      </text>
    );
  };
}

// Horizontal bars, best on top, each with its value at its end; the title says which way is
// better. One series: the focus method in the accent; several: the series' colors, named above.
function Bars({
  data,
  x,
  series,
  stacked = false,
  percent = false,
  error,
  title,
  better,
}: {
  data: Row[];
  x: string;
  series: { key: string; name: string; color?: string }[];
  stacked?: boolean;
  percent?: boolean;
  error?: string;
  title: string;
  better: "higher" | "fewer";
}) {
  const presenting = useContext(Presenting);
  if (!data.length) return <Empty>Nothing to chart.</Empty>;
  const format = (v: number) => (percent ? `${Math.round(v * 100)}%` : formatNumber(v));
  const keys = series.map((s) => s.key);
  const total = (d: Row) => keys.reduce((sum, k) => sum + (Number(d[k]) || 0), 0);
  const rows = [...data].sort((a, b) => (better === "fewer" ? total(a) - total(b) : total(b) - total(a)));
  const grouped = series.length > 1 && !stacked;
  const rowHeight = (presenting ? 40 : 28) * (grouped ? series.length * 0.8 : 1);
  const nameWidth = Math.min(Math.max(...rows.map((d) => String(d[x]).length)) * (presenting ? 10 : 7.6) + 16, presenting ? 280 : 200);
  const colors = series.map((s, i) => s.color ?? (series.length === 1 ? "var(--muted)" : `var(--series-${i + 1})`));
  const most = Math.max(...rows.map((d) => (stacked ? total(d) : Math.max(...keys.map((k) => Number(d[k]) || 0))) + (error ? Number((d[error] as number[])?.[1]) || 0 : 0)));
  return (
    <div className="chart" role="img" aria-label={title}>
      <div className="chart-title">
        {title} <span className="better">({better === "fewer" ? "fewer is better" : "higher is better"})</span>
      </div>
      {series.length > 1 && <SeriesKey series={series.map((s, i) => ({ name: s.name, color: colors[i] }))} />}
      <ResponsiveContainer width="100%" height={rows.length * rowHeight + 16}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: presenting ? 72 : 56, bottom: 4, left: 0 }} barCategoryGap="22%">
          <XAxis type="number" hide domain={[0, percent ? Math.max(1, most) : most || 1]} />
          <YAxis type="category" dataKey={x} width={nameWidth} tick={nameTick(nameWidth)} tickLine={false} axisLine={false} interval={0} />
          <Tooltip contentStyle={TOOLTIP} formatter={(v) => format(Number(v))} cursor={{ fill: "var(--grid)", opacity: 0.4 }} />
          {series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.name}
              stackId={stacked ? "one" : undefined}
              fill={colors[i]}
              stroke="var(--surface)"
              strokeWidth={stacked ? 1 : 0}
              minPointSize={series.length === 1 ? 2 : 0}
              radius={stacked && i < series.length - 1 ? 0 : [0, 3, 3, 0]}
              isAnimationActive={ANIMATE}
            >
              {series.length === 1 && rows.map((d) => <Cell key={String(d[x])} fill={d[x] === FOCUS ? "var(--accent)" : colors[0]} />)}
              {error && i === 0 && <ErrorBar dataKey={error} direction="x" width={6} stroke="var(--text)" />}
              {!stacked && <LabelList valueAccessor={nameOf(x)} content={valueAtEnd(rows, x, s.key, format, i === 0 ? error : undefined)} />}
              {stacked && <LabelList valueAccessor={nameOf(x)} content={stackTotal(rows, x, keys, s.key, format, true)} />}
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
                <Bars data={bars} x="method" series={[{ key: "share", name: "planted slop removed" }]} percent error="ci" title="Planted slop removed per run (mean, 95% CI)" better="higher" />
                <Bars data={bars} x="method" series={[{ key: "traps", name: "traps removed" }]} title="Traps removed: each one changes behavior" better="fewer" />
              </div>
            );
          }}
        </Loaded>
        <p className="muted">All seeds pooled, with a bootstrap CI over project and seed. The table has each seed.</p>
      </Card>
      <Card title="By seed and pooled">
        <Loaded name="injection_seeds.csv">{(t) => <DataTable table={t} names={NAMES} label="injection_seeds.csv" maxHeight={320} />}</Loaded>
      </Card>
      <Card title="The team against the other methods, paired by project and seed">
        <Loaded name="injection_paired.csv">{(t) => <DataTable table={t} names={NAMES} label="injection_paired.csv" />}</Loaded>
      </Card>
      <Card title="The extended framework rule, re-scored (as run and with the rule)">
        <Loaded name="inject_rule.csv">{(t) => <DataTable table={t} names={NAMES} label="inject_rule.csv" />}</Loaded>
        <p className="muted">In-sample: the rule was extended after seeing these wrong edits and is re-scored on the same runs, so the drop is optimistic until fresh projects or seeds test it.</p>
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
        <Bars data={bars} x="method" series={[{ key: "llm", name: "LLM requests" }]} title="LLM requests per run (mean)" better="fewer" />
        <Bars data={bars} x="method" series={[{ key: "minutes", name: "minutes" }]} title="Minutes per run (median)" better="fewer" />
      </div>
    </>
  );
}

function Ablations() {
  return (
    <>
      <Card title="Real projects: the team, no research squad, a single agent">
        <Loaded name="real_ablation.csv">{(t) => <DataTable table={t} names={NAMES} label="real_ablation.csv" />}</Loaded>
        <p className="muted">Wrong edits count all tiers, with those confirmed by a test, check or rule in brackets; the debatable edits and the LLM reviewer's acceptance are LLM-judged. The table scrolls sideways for the UI check, requests and minutes.</p>
        <p className="muted">Five projects, one run each, with every wrong edit in three of them: these differences suggest, but don't establish, that investigating each candidate pays off on real code. Fisher's exact test against the team:</p>
        <Loaded name="real_ablation_tests.csv">{(t) => <DataTable table={t} names={NAMES} label="real_ablation_tests.csv" />}</Loaded>
      </Card>
      <Card title="Ablations on the answer keys, SWE-bench, AIDev and the injected set">
        <Loaded name="ablations.csv">{(t) => <AblationCost rows={records(t)} />}</Loaded>
        <Loaded name="ablations.csv">{(t) => <DataTable table={t} names={NAMES} label="ablations.csv" maxHeight={360} />}</Loaded>
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
          better="fewer"
        />
        <Bars data={kindBars(types, source)} x="method" stacked series={KINDS.map((k, i) => ({ key: k, name: k, color: KIND_COLORS[i] }))} title="Wrong edits by kind (count)" better="fewer" />
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
        An independent model flagged kept edits; each flag was then checked. Confirmed means a targeted test in the run's own environment, the UI check, or the injection key's or agent patch's rule; reading means the check is LLM-judged. The auditor never sees the method, so the counts are lower bounds (edits it does not flag stay unchecked) that its method labels cannot bias, though the share left unchecked differs by method.
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
              better="higher"
            />
            <DataTable table={t} names={NAMES} label="probe_strength.csv" />
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
              better="higher"
            />
            <DataTable table={t} names={NAMES} label="manager_scenarios.csv" />
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
            <Bars data={reviewBars(records(t))} x="project" percent series={[{ key: "acceptance", name: "accepted" }]} title="Changes the LLM reviewer accepts, per project (LLM-judged)" better="higher" />
            <DataTable table={t} names={NAMES} label="llm_review_acceptance.csv" maxHeight={320} />
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
                <Bars data={bars} x="policy" series={[{ key: "debt", name: "slop debt per commit" }]} title="Slop debt per commit (mean over repositories)" better="fewer" />
                <Bars data={bars} x="policy" series={[{ key: "tests", name: "test runs" }]} title="Test runs spent (mean over repositories)" better="fewer" />
              </div>
              <DataTable table={t} names={NAMES} label="watch_replay.csv" maxHeight={280} />
            </>
          );
        }}
      </Loaded>
    </Card>
  );
}

const V3_NOTE = "The hypotheses are tested as the Phase 3 pre-registration states them.";

function V3Table({ name }: { name: string }) {
  return <Loaded name={name} version="v3">{(t) => <DataTable table={t} names={NAMES} label={name} maxHeight={360} />}</Loaded>;
}

function V3Hypotheses() {
  return (
    <Card title="H1–H4, as pre-registered">
      <V3Table name="hypotheses.csv" />
      <p className="muted">{V3_NOTE} Each is supported, not supported, or not run by the freeze.</p>
    </Card>
  );
}

function V3Injection() {
  return (
    <>
      <Card title="INJECT, seed 4 (out of sample): planted slop removed">
        <Loaded name="injection.csv" version="v3">
          {(t) => <Bars data={v3RecallBars(records(t))} x="method" series={[{ key: "share", name: "planted slop removed" }]} percent error="ci" title="Planted slop removed (95% interval over repositories)" better="higher" />}
        </Loaded>
        <p className="muted">A run that hit the cap or the budget is timed out: it stays in the denominator and removes nothing. {V3_NOTE}</p>
      </Card>
      <Card title="Per method">
        <V3Table name="injection.csv" />
      </Card>
    </>
  );
}

function V3Real() {
  return (
    <>
      <Card title="REAL, run 1: held-out real tests and visible breaks">
        <V3Table name="real.csv" />
        <p className="muted">Half of each project's own test modules are held out (seed 4); only tests that pass in all three baseline runs count. {V3_NOTE}</p>
      </Card>
      <Card title="Safety against yield">
        <V3Table name="curve.csv" />
        <p className="muted">Wrong edits in all tiers include readings (LLM-judged); the confirmed tier rests on targeted tests, the UI check and rules.</p>
      </Card>
    </>
  );
}

function V3Audit() {
  return (
    <>
      <Card title="The blinded diff audit on the Phase 3 runs, two tiers">
        <V3Table name="audit.csv" />
        <p className="muted">{judged("reading tier: LLM-judged")} Counts on finished runs; Fisher's exact test against the team.</p>
      </Card>
      <Card title="What the audit misses (estimate)">
        <V3Table name="audit_miss.csv" />
        <p className="muted">Targeted tests on a stratified sample of edits the auditor voted "no"; every number here is an estimate.</p>
      </Card>
      <Card title="LLM judge panel">
        <V3Table name="judge_panel.csv" />
        <p className="muted">
          Three LLM judges from other model families (gpt-oss-120b, llama4-maverick-17b, gemma4-31b-it) rate the blinded 100-item packet: their
          agreement, and their accuracy on test-confirmed verdicts. LLM-judged: no human checked these labels.
        </p>
      </Card>
    </>
  );
}

function V3Autonomy() {
  return (
    <>
      <Card title="AUTONOMY: clean on 30 diverse repositories, no human help">
        <V3Table name="autonomy.csv" />
        <p className="muted">Completed means a cleanup verdict; "stopped" is a valid ending but not completed. The raw rate decides H4 and R19; the rate without environment-impossible runs is shown beside it.</p>
      </Card>
      <Card title="Cost per finished run">
        <V3Table name="cost.csv" />
      </Card>
    </>
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
    "v3-hypotheses": <V3Hypotheses />,
    "v3-injection": <V3Injection />,
    "v3-real": <V3Real />,
    "v3-audit": <V3Audit />,
    "v3-autonomy": <V3Autonomy />,
  };
  const presenting = useContext(Presenting);
  const at = TABS.findIndex((t) => t.key === active);
  const phase = TABS[at].phase;
  const here = `#/evaluation?${new URLSearchParams({ tab: active })}`;
  return (
    <div className="screen evaluation">
      <PageHeader
        title="Evaluation"
        description="The Phase 2 and Phase 3 results, charted from the committed tables."
        help="One tab per experiment, read from results/summary/v2/ and v3/. Each bar carries its value, the team in the accent; anything an LLM judged says LLM-judged."
        actions={
          presenting ? (
            <a className="button" href={here}>
              Exit <kbd>Esc</kbd>
            </a>
          ) : (
            <a className="button" href={`${here}&present=1`}>
              Present
            </a>
          )
        }
      />
      {presenting ? (
        <PresentNav at={at} onTab={onTab} exit={here} />
      ) : (
        <div className="eval-nav">
          <div className="view-switch" role="group" aria-label="Phase">
            {PHASES.map((p) => (
              <button key={p} type="button" aria-pressed={p === phase} onClick={() => p !== phase && onTab(TABS.find((t) => t.phase === p)!.key)}>
                {p}
              </button>
            ))}
          </div>
          <Tabs tabs={TABS.filter((t) => t.phase === phase)} value={active} onChange={onTab} />
        </div>
      )}
      {screens[active]}
    </div>
  );
}

// Presentation mode: one line instead of the tabs; the arrow keys move between them and Escape
// leaves.
function PresentNav({ at, onTab, exit }: { at: number; onTab: (tab: string) => void; exit: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") window.location.hash = exit;
      else if (e.key === "ArrowRight" && at < TABS.length - 1) onTab(TABS[at + 1].key);
      else if (e.key === "ArrowLeft" && at > 0) onTab(TABS[at - 1].key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [at, exit]);
  const t = TABS[at];
  return (
    <p className="present-nav" aria-live="polite">
      {t.phase} · <b>{t.label}</b> · {at + 1} of {TABS.length}{" "}
      <span className="muted">
        <kbd>←</kbd>/<kbd>→</kbd>
      </span>
    </p>
  );
}
