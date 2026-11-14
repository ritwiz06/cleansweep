// Chart data for the Evaluation screen, from the committed tables (results/summary/v2/ and v3/).
import type { Table } from "../api";

export type Row = Record<string, unknown>;

export const METHOD_NAMES: Record<string, string> = {
  agentic: "team",
  team: "team",
  "agentic (thorough)": "team (thorough)",
  "agentic-no_research": "no research squad",
  no_research: "no research squad",
  "agentic-single_agent": "single agent",
  single_agent: "single agent",
  "agentic-rules": "rule-based Manager",
  "agentic-adaptive": "adaptive investigation",
  adaptive: "adaptive investigation",
  "agentic-broadcast": "broadcast",
  "agentic-inline_artifacts": "inline artifacts",
  "agentic-no_lessons": "no lessons",
  "agentic-no_coverage": "no coverage",
  cleansweep: "Phase 1 pipeline",
  "cleansweep-gatekeeper": "Phase 1 pipeline",
  "agentic-no_resolver": "team, resolver off",
  "agentic-batch": "team, batching",
  "agentic-thorough": "team, thorough",
  "agentic-m2": "team, second model",
  "agentic-single_agent-m2": "single agent, second model",
  aider: "Aider",
  "cleansweep-advisory": "Phase 1 pipeline (advisory)",
  one_shot_llm: "one-shot",
};

export const KINDS = ["dynamic handler or stub", "public name", "changed logic", "deleted file", "dependency", "other"];

export function methodName(method: unknown): string {
  return METHOD_NAMES[String(method)] ?? String(method);
}

export function records(table: Table | null | undefined): Row[] {
  if (!table) return [];
  return table.rows.map((row) => Object.fromEntries(table.columns.map((c, i) => [c, row[i]])));
}

export function num(value: unknown): number {
  const n = typeof value === "number" ? value : Number.parseFloat(String(value ?? ""));
  return Number.isFinite(n) ? n : 0;
}

// "0.714 [0.600, 0.829]" -> {mean, low, high}
export function parseCI(text: unknown): { mean: number; low: number; high: number } | null {
  const m = String(text ?? "").match(/^\s*(-?[\d.]+)\s*\[\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\]/);
  return m ? { mean: Number(m[1]), low: Number(m[2]), high: Number(m[3]) } : null;
}

// "50/70" -> {n: 50, d: 70}
export function ratio(text: unknown): { n: number; d: number } | null {
  const m = String(text ?? "").match(/^\s*(\d+)\s*\/\s*(\d+)/);
  return m ? { n: Number(m[1]), d: Number(m[2]) } : null;
}

// The injection benchmark per method: the pooled row, or the only seed when there is one.
export function injectionBars(rows: Row[]) {
  const pooled = rows.some((r) => r.seeds === "pooled");
  return rows
    .filter((r) => (pooled ? r.seeds === "pooled" : true))
    .map((r) => {
      const ci = parseCI(r["share per run (mean, 95% CI)"]);
      const share = ci?.mean ?? 0;
      return {
        method: methodName(r.method),
        share,
        ci: ci ? [share - ci.low, ci.high - share] : [0, 0],
        traps: num(r["traps removed"]),
        runs: num(r.runs),
      };
    });
}

// v3's injection.csv: recall with its bootstrap interval over repositories, per method
export function v3RecallBars(rows: Row[]) {
  return rows
    .filter((r) => String(r.recall ?? "") !== "")
    .map((r) => {
      const share = num(r.recall);
      return {
        method: methodName(r.method),
        share,
        ci: [share - num(r.recall_ci_low), num(r.recall_ci_high) - share],
        timedOut: num(r.timed_out),
      };
    });
}

export function sources(rows: Row[], column = "source"): string[] {
  return [...new Set(rows.map((r) => String(r[column])))];
}

// real_ablation.csv's wrong kept code edits per method, all tiers: "4 of 20 (3)" -> 4.
export function realAblationBars(rows: Row[]) {
  const column = Object.keys(rows[0] ?? {}).find((c) => c.startsWith("wrong of kept code edits"));
  if (!column) return [];
  return rows.map((r) => ({ method: methodName(r.method), wrong: num(String(r[column]).match(/^\d+/)?.[0]) }));
}

// LLM requests and minutes per run of each method, for one target set of the ablations.
export function costBars(rows: Row[], set: string) {
  return rows
    .filter((r) => r.set === set)
    .map((r) => ({ method: methodName(r.method), llm: num(r["LLM requests (mean)"]), minutes: num(r["minutes (median)"]) }));
}

// Wrong edits per 100 kept code edits, split by tier, for one target set of the diff audit.
export function auditBars(rows: Row[], source: string) {
  return rows
    .filter((r) => r.source === source && num(r.kept_code_edits) > 0)
    .map((r) => {
      const per = 100 / num(r.kept_code_edits);
      return {
        method: methodName(r.method),
        confirmed: round(num(r.wrong_confirmed) * per),
        reading: round(num(r.wrong_reading) * per),
        debatable: round(num(r.debatable) * per),
        kept: num(r.kept_code_edits),
        wrong: num(r.wrong),
      };
    });
}

// Wrong (or debatable) edits of each method by kind, for one target set.
export function kindBars(rows: Row[], source: string, verdict = "wrong") {
  const out = new Map<string, Row>();
  for (const r of rows) {
    if (r.source !== source || r.verdict !== verdict) continue;
    const name = methodName(r.method);
    const bar = out.get(name) ?? { method: name, ...Object.fromEntries(KINDS.map((k) => [k, 0])) };
    bar[String(r.kind)] = num(bar[String(r.kind)]) + num(r.kept_code_edits);
    out.set(name, bar);
  }
  return [...out.values()];
}

const SETS: Record<string, string> = { swebench_t1: "SWE-bench T1", swebench_t2_v2subset: "SWE-bench T2" };

export function probeBars(rows: Row[]) {
  return rows.map((r) => ({
    label: `${SETS[String(r.target_set)] ?? r.target_set}: ${r.experiment === "mutation" ? "mutants" : "PatchDiff"}`,
    tests: num(r.share_by_tests),
    probes: num(r.share_by_probes),
    n: num(r.n),
  }));
}

// Accuracy per scenario, one key per Manager.
export function scenarioBars(rows: Row[]) {
  const out = new Map<string, Row>();
  for (const r of rows) {
    const bar = out.get(String(r.scenario)) ?? { scenario: String(r.scenario) };
    bar[String(r.manager)] = num(r.accuracy);
    out.set(String(r.scenario), bar);
  }
  return [...out.values()];
}

// Overall acceptance per project (the "all" rows), LLM-judged.
export function reviewBars(rows: Row[]) {
  return rows
    .filter((r) => r.mode === "all" && r.category === "all")
    .map((r) => ({ project: String(r.project), acceptance: num(r.acceptance), rows: num(r.rows) }));
}

// Mean slop debt per commit and the test runs each sweep policy spent, over the replayed repositories.
export function watchBars(rows: Row[]) {
  const out = new Map<string, { policy: string; debt: number; tests: number; repos: number }>();
  for (const r of rows) {
    const key = String(r.policy);
    const bar = out.get(key) ?? { policy: key, debt: 0, tests: 0, repos: 0 };
    bar.debt += num(r.slop_debt_per_commit);
    bar.tests += num(r.test_runs_est);
    bar.repos += 1;
    out.set(key, bar);
  }
  return [...out.values()].map((b) => ({ ...b, debt: round(b.debt / b.repos), tests: round(b.tests / b.repos) }));
}

function round(x: number): number {
  return Math.round(x * 100) / 100;
}
