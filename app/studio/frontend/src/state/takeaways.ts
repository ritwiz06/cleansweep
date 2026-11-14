// One plain sentence per Evaluation tab, read from the same rows its chart or table draws. Each
// returns null when the rows it needs are not there, and the tab then shows no sentence.
import { auditBars, injectionBars, methodName, num, probeBars, reviewBars, scenarioBars, v3RecallBars, watchBars, type Row } from "./evaluation";

const pct = (share: number) => `${Math.round(share * 100)}%`;
const TEAM = "team";

function most<T>(rows: T[], by: (row: T) => number): T | undefined {
  return rows.reduce<T | undefined>((best, r) => (best === undefined || by(r) > by(best) ? r : best), undefined);
}

export function injectionTakeaway(bars: ReturnType<typeof injectionBars>): string | null {
  const team = bars.find((b) => b.method === TEAM);
  if (!team) return null;
  const worst = most(
    bars.filter((b) => b.method !== TEAM),
    (b) => b.traps,
  );
  const traps = team.traps === 0 ? "deleted no trap" : `deleted ${team.traps} traps`;
  const other = worst && worst.traps > 0 ? `; ${worst.method} deleted ${worst.traps}` : "";
  return `The team removed ${pct(team.share)} of the planted slop and ${traps}${other}.`;
}

// real_ablation.csv: "0 of 14 (0)" -> "0 of 14"
export function realAblationTakeaway(rows: Row[]): string | null {
  const column = Object.keys(rows[0] ?? {}).find((c) => c.startsWith("wrong of kept code edits"));
  if (!column) return null;
  const parts = rows.map((r) => `${methodName(r.method)} ${String(r[column]).match(/^\d+ of \d+/)?.[0] ?? r[column]}`);
  return `Wrong edits among the kept code edits on real projects: ${parts.join(", ")}.`;
}

export function auditTakeaway(rows: Row[], source: string): string | null {
  const bars = auditBars(rows, source);
  const team = bars.find((b) => b.method === TEAM);
  if (!team) return null;
  const wrong = (b: (typeof bars)[number]) => b.confirmed + b.reading;
  const worst = most(
    bars.filter((b) => b.method !== TEAM),
    wrong,
  );
  const other = worst ? `; ${worst.method}, ${Math.round(wrong(worst))}` : "";
  return `Per 100 kept code edits, the team made ${Math.round(wrong(team))} wrong edits${other}.`;
}

export function probeTakeaway(rows: Row[]): string | null {
  const bars = probeBars(rows).filter((b) => b.n > 0);
  if (!bars.length) return null;
  const tests = bars.reduce((s, b) => s + b.tests * b.n, 0);
  const probes = bars.reduce((s, b) => s + b.probes * b.n, 0);
  const n = bars.reduce((s, b) => s + b.n, 0);
  return `Over ${n} planted changes, the tests catch ${pct(tests / n)} and the probes catch ${pct(probes / n)} more.`;
}

export function managerTakeaway(rows: Row[]): string | null {
  const bars = scenarioBars(rows);
  if (!bars.length) return null;
  const right = (key: string) => bars.filter((b) => num(b[key]) === 1).length;
  return `The LLM Manager got every run right in ${right("llm")} of ${bars.length} scenarios, the rule-based one in ${right("rules")}.`;
}

export function reviewerTakeaway(rows: Row[]): string | null {
  const bars = reviewBars(rows);
  if (!bars.length) return null;
  const shares = bars.map((b) => b.acceptance);
  return `The LLM reviewer accepts ${pct(Math.min(...shares))} to ${pct(Math.max(...shares))} of each project's changes (LLM-judged).`;
}

export function watchTakeaway(rows: Row[]): string | null {
  const bars = watchBars(rows);
  const watch = bars.find((b) => b.policy === "watch");
  const none = bars.find((b) => b.policy === "none");
  if (!watch) return null;
  const never = none ? `; never cleaning leaves ${none.debt}` : "";
  return `Watch keeps the slop debt at ${watch.debt} per commit for ${watch.tests} test runs${never}.`;
}

export function hypothesesTakeaway(rows: Row[]): string | null {
  if (!rows.length || !("hypothesis" in rows[0])) return null;
  return `${rows.map((r) => `${r.hypothesis} ${r.result}`).join(", ")}.`;
}

export function v3InjectionTakeaway(rows: Row[]): string | null {
  const bars = v3RecallBars(rows);
  const team = bars.find((b) => b.method === TEAM);
  if (!team) return null;
  const best = most(
    bars.filter((b) => b.method !== TEAM),
    (b) => b.share,
  );
  const other = best ? `; the best other method, ${best.method}, ${pct(best.share)}` : "";
  return `On the out-of-sample seed the team removed ${pct(team.share)} of the planted slop${other}.`;
}

export function realTakeaway(rows: Row[]): string | null {
  const team = rows.find((r) => methodName(r.method) === TEAM);
  if (!team || !("heldout_changed_projects (finished)" in team)) return null;
  const finished = num(team.finished);
  return `The team's edits changed held-out tests on ${num(team["heldout_changed_projects (finished)"])} of ${finished} finished projects and visibly broke ${num(team["visible_broken_projects (finished)"])}.`;
}

export function v3AuditTakeaway(rows: Row[]): string | null {
  const team = rows.filter((r) => methodName(r.method) === TEAM);
  if (!team.length || !("wrong_confirmed" in team[0])) return null;
  const kept = team.reduce((s, r) => s + num(r.kept_code_edits), 0);
  const all = team.reduce((s, r) => s + num(r["wrong_all_tiers (incl. LLM-judged readings)"]), 0);
  const confirmed = team.reduce((s, r) => s + num(r.wrong_confirmed), 0);
  return `Of the team's ${kept} kept code edits, ${all} are wrong in all tiers (LLM-judged readings included) and ${confirmed} confirmed by a test, check or rule.`;
}

export function autonomyTakeaway(rows: Row[]): string | null {
  const first = rows[0];
  if (!first || !("completed" in first)) return null;
  return `With no help, ${num(first.completed)} of ${num(first.runs)} runs on diverse repositories ended with a cleanup verdict (${pct(num(first.rate))}).`;
}
