// Which applied candidate each hunk of the final diff comes from, and the decisions, evidence
// and checks behind it.
import type { DiffFile, Hunk } from "./diff";
import type { Item, Package, RunState } from "./fold";
import { plural } from "./labels";
import { splitUnit } from "./tree";

export const CATEGORY_LABEL: Record<string, string> = {
  leftover_file: "leftover file",
  dead_code: "dead code",
  duplicate: "duplicate",
  wrapper: "wrapper",
  unused_import: "unused import",
  unused_dependency: "unused dependency",
  unused_variable: "unused variable",
  format: "formatting",
  security: "security",
  debug_leftover: "debug print",
  commented_code: "commented-out code",
  todo_note: "TODO note",
  redundant_check: "redundant check",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] || category.replace(/_/g, " ");
}

// "exact": the hunk names the candidate (or covers its lines); "only": the one candidate applied
// in this file; "file": several were, and the hunk names none of them.
export interface HunkNote {
  items: string[];
  match: "exact" | "only" | "file" | "none";
}

const APPLIED = ["kept", "repaired"];

function word(text: string, name: string): boolean {
  return new RegExp(`(^|[^\\w])${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^\\w]|$)`).test(text);
}

function names(item: Item, hunk: Hunk, file: DiffFile): boolean {
  const { rest } = splitUnit(item.unit);
  if (!rest) return file.status === "removed";
  const changed = hunk.lines.filter((l) => l[0] === "-" || l[0] === "+").map((l) => l.slice(1));
  const removed = hunk.lines.filter((l) => l[0] === "-").map((l) => l.slice(1));
  const lines = /^L(\d+)-(\d+)$/.exec(rest);
  if (lines) {
    const end = hunk.oldStart + Math.max(hunk.oldCount, 1) - 1;
    return Number(lines[1]) <= end && Number(lines[2]) >= hunk.oldStart;
  }
  const name = rest.split(".").pop() || rest;
  if (item.category === "unused_import") return removed.some((l) => /\bimport\b/.test(l) && word(l, name));
  if (item.category === "unused_dependency") return removed.some((l) => word(l, name));
  if (item.category === "dead_code") return removed.some((l) => new RegExp(`^\\s*(async\\s+)?(def|class)\\s+${name}\\b`).test(l));
  return changed.some((l) => word(l, name));
}

export function annotateFile(file: DiffFile, state: RunState): HunkNote[] {
  const here = state.itemOrder
    .map((id) => state.items[id])
    .filter((item) => APPLIED.includes(item.stage) && [file.path, file.oldPath].includes(splitUnit(item.unit).path));
  return file.hunks.map((hunk) => {
    const exact = here.filter((item) => names(item, hunk, file));
    if (exact.length) return { items: exact.map((i) => i.id), match: "exact" };
    // a file-level edit (formatting) owns whatever no other candidate explains
    const whole = here.filter((item) => !splitUnit(item.unit).rest);
    if (whole.length) return { items: whole.map((i) => i.id), match: "exact" };
    if (here.length === 1) return { items: [here[0].id], match: "only" };
    return { items: here.map((i) => i.id), match: here.length ? "file" : "none" };
  });
}

export interface Step {
  agent: string;
  text: string;
  brief: string; // two or three words, for a chain of icons
}

// The decisions behind an applied candidate, agent by agent, from the events.
export function decisionSteps(item: Item, state: RunState): Step[] {
  const steps: Step[] = [{ agent: "auditor", text: `flagged it as ${categoryLabel(item.category)} (${item.lane} lane)`, brief: categoryLabel(item.category) }];
  const v = item.verdict;
  if (v) {
    const sure = v.confidence !== null && v.confidence > 0 ? ` (confidence ${v.confidence})` : "";
    steps.push({ agent: v.agent || "investigator", text: `${v.decision}${sure}: ${v.reason}`, brief: `${v.decision}${sure}` });
  }
  const pkg = item.pkg ? state.packages[item.pkg] : null;
  if (!pkg) return steps;
  steps.push({ agent: "planner", text: `put it in ${pkg.id}${pkg.goal ? `: ${pkg.goal}` : ""}`, brief: pkg.id });
  const commit = pkg.commit ? ` (commit ${pkg.commit.slice(0, 8)})` : "";
  steps.push({ agent: "engineer", text: pkg.applied.includes(item.id) ? `applied the edit${commit}` : "applied the package", brief: "applied" });
  for (const t of pkg.tests) {
    const failed = `${t.stage}: failed (${t.newFailures.join(", ") || "see the log"})`;
    steps.push({ agent: "tester", text: t.ok ? `${t.stage}: passed` : failed, brief: t.ok ? "tests pass" : "tests fail" });
  }
  if (pkg.validation) {
    const p = pkg.validation.probes;
    const probes = p ? `${plural(p.n_cases, "probe case")}, ${p.same ? "same behavior" : `${(p.mismatches || []).length} differ`}` : "no probes";
    const brief = p ? `${p.n_cases} probes, ${p.same ? "same" : "differ"}` : pkg.validation.ok ? "checks pass" : "checks fail";
    steps.push({ agent: "validator", text: `${pkg.validation.ok ? "passed" : "failed"}: ${probes}`, brief });
  }
  if (pkg.repair) {
    const outcome = pkg.repair.outcome.replace(/_/g, " ");
    steps.push({ agent: "fixer", text: `${outcome}${pkg.repair.turns ? ` after ${pkg.repair.turns} turns` : ""}`, brief: outcome });
  }
  const done = state.decisions.find((d) => d.rule === "package_done" && d.pkg === pkg.id);
  // in words, not the package id: "kept the change", "rolled back the change"
  if (done) steps.push({ agent: done.agent || "manager", text: done.status ? `${done.status.replace(/_/g, " ")} the change` : done.text, brief: (done.status || "done").replace(/_/g, " ") });
  return steps;
}

export interface Check {
  label: string;
  ok: boolean | null | "warn";
}

// The checks a package passed (ok), failed (not ok), did not run (null), or passed with
// something for a person to look at (warn: a kept package that removes public names).
export function packageChecks(pkg: Package): Check[] {
  const out: Check[] = [];
  const last = pkg.tests[pkg.tests.length - 1];
  out.push(last ? { label: last.ok ? "tests pass" : "tests fail", ok: last.ok } : { label: "tests not run", ok: null });
  const p = pkg.validation?.probes;
  if (p) out.push({ label: `${plural(p.n_cases, "probe case")}: ${p.same ? "same before and after" : "behavior differs"}`, ok: Boolean(p.same) });
  if (typeof pkg.coverage === "number") out.push({ label: `probe coverage of the changed lines ${Math.round(pkg.coverage * 100)}%`, ok: pkg.coverage >= 0.9 ? true : null });
  const api = pkg.validation?.checks?.public_api_removed;
  if (Array.isArray(api)) {
    const removes = `Removes ${plural(api.length, "public name")}: ${api.join(", ")}. Check that nothing outside the project uses ${api.length === 1 ? "it" : "them"}.`;
    out.push(api.length ? { label: removes, ok: "warn" } : { label: "public names unchanged", ok: true });
  }
  const ui = pkg.ui || pkg.validation?.checks?.ui;
  if (ui && !String(ui).startsWith("not applicable")) out.push({ label: `UI check: ${ui}`, ok: !/fail/i.test(String(ui)) });
  return out;
}
