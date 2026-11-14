// One plain line per step of a run, for presentation mode: "Investigator #3 checks who calls
// parse_args()". Events that change nothing a viewer can follow (LLM waits, raw results) get none.
import { categoryLabel } from "./annotate";
import { agentName, newFolder, roleOf, step, type Item, type RunState, type StudioEvent } from "./fold";
import { isDecision } from "./replay";
import { splitUnit } from "./tree";

export interface Caption {
  agent: string;
  text: string;
  detail?: string;
}

export interface CaptionStep extends Caption {
  index: number; // the event's position in the log
  t: number;
  decision: boolean;
}

const PHASE_LABEL: Record<string, string> = {
  ONBOARD: "onboarding",
  BASELINE: "the baseline",
  AUDIT: "the audit",
  INVESTIGATE: "investigation",
  PLAN: "planning",
  EXECUTE: "execution",
  FINAL_VERIFY: "the final check",
  REPORT: "the report",
  DONE: "done",
};

const DONE_TEXT: Record<string, string> = {
  kept: "keeps",
  repaired: "keeps (repaired)",
  rolled_back: "rolls back",
  skipped: "skips",
};

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function lower(text: string): string {
  return text ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

// A reason, cut only at the end of a sentence: as many whole sentences as fit in about two lines
// of a caption, and always at least the first one.
export function short(text: string, n = 200): string {
  const one = text.replace(/\s+/g, " ").trim();
  const sentences = one.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) || [one];
  let out = sentences[0].trim();
  for (const s of sentences.slice(1)) {
    if ((out + s).length > n) break;
    out += s;
  }
  return out.trim();
}

// How a candidate reads in a sentence: a file's path, a function with (), "line 37 of x.py".
export function itemLabel(item: Item): string {
  const { path, rest } = splitUnit(item.unit);
  if (!rest) return path;
  const lines = /^L(\d+)-(\d+)$/.exec(rest);
  if (lines) return lines[1] === lines[2] ? `line ${lines[1]} of ${path}` : `lines ${lines[1]}–${lines[2]} of ${path}`;
  if (item.category === "unused_import") return `import ${rest}`;
  if (item.category === "unused_dependency") return rest;
  const name = rest.split(".").pop()!;
  return /^[A-Z]/.test(name) ? name : `${name}()`;
}

// A name an investigator's tool call asks about, as the candidate it belongs to reads.
function named(s: RunState, name: string): { label: string; fn: boolean } {
  for (const id of s.itemOrder) {
    const item = s.items[id];
    const { path, rest } = splitUnit(item.unit);
    const last = rest?.split(".").pop();
    if (last === name && !/^L\d/.test(rest || "")) return { label: itemLabel(item), fn: !/^[A-Z]/.test(name) && item.category !== "unused_import" };
    if (!rest && (path === name || path.split("/").pop()?.replace(/\.py$/, "") === name)) return { label: path, fn: false };
  }
  return { label: name, fn: false };
}

function tool(e: StudioEvent, s: RunState): string | null {
  const p = e.payload || {};
  const a = p.args || {};
  switch (p.tool) {
    case "find_references": {
      const n = named(s, a.name);
      return n.fn ? `checks who calls ${n.label}` : `checks who uses ${n.label}`;
    }
    case "check_dynamic_use":
      return `checks whether anything reaches ${named(s, a.name).label} by name`;
    case "read_code":
    case "read_file":
      return a.start_line && a.end_line ? `reads ${a.path}, lines ${a.start_line}–${a.end_line}` : `reads ${a.path}`;
    case "query_lessons":
      return `looks for lessons about ${a.pattern}`;
    case "compare_functions":
      return `compares ${String(a.a).split("::").pop()} with ${String(a.b).split("::").pop()}`;
    case "find_related_tests":
      return `finds the tests that cover ${a.path}`;
    case "check_dependency_usage":
      return `checks whether anything imports ${a.package}`;
    case "query_knowledge_base":
      return `asks the knowledge base about ${categoryLabel(a.category || "slop")}`;
    case "run_tests":
      return e.phase === "BASELINE" && a.run ? `runs the tests (run ${a.run} of 3)` : "runs the tests";
    case "install":
      return "installs the project in its own environment";
    case "run_detectors":
      return "runs the detectors";
    case "run_line_detectors":
      return "runs the line-level detectors";
    case "apply_edit": {
      const item = s.items[a.item];
      const what = item ? itemLabel(item) : a.item;
      const verb: Record<string, string> = {
        delete_file: `deletes ${what}`,
        delete_unit: `removes ${what}`,
        replace_with: `replaces ${what} with the original it duplicates`,
        remove_import: `removes the unused ${what}`,
        remove_dependency: `removes the dependency ${what}`,
        edit_lines: `edits ${what}`,
      };
      return verb[a.action] || `applies ${String(a.action).replace(/_/g, " ")} to ${what}`;
    }
  }
  return null;
}

function message(e: StudioEvent, s: RunState): Caption | null {
  const p = e.payload || {};
  const b = p.body || {};
  const from = e.agent || "manager";
  const to = (e.recipients || [])[0] || "";
  const pkg = b.package ? s.packages[b.package] : null;
  switch (p.type) {
    case "task":
      if (roleOf(to) === "investigator" && b.items?.length) return { agent: from, text: `asks the Investigators to look at ${plural(b.items.length, "candidate")}` };
      if (!b.goal) return null;
      return { agent: from, text: `asks the ${agentName(roleOf(to))} to ${lower(b.goal).replace(/(P\d+): (\w)/, (_m, id, c) => `${id}: ${c.toLowerCase()}`)}` };
    case "brief": {
      const n = s.facts?.python_files;
      return { agent: from, text: `writes the brief${n ? `: ${plural(n, "Python file")}` : ""}${b.test_command ? `, tests run with ${b.test_command}` : ""}` };
    }
    case "baseline":
      return { agent: from, text: `measures the baseline (3 runs): ${b.passed ?? 0} pass, ${(b.failed ?? 0) + (b.errors ?? 0)} fail, ${(b.flaky || []).length} flaky` };
    case "candidates": {
      const counts: Record<string, number> = {};
      for (const c of b.items || []) counts[c.category] = (counts[c.category] || 0) + 1;
      const top = Object.entries(counts).sort((x, y) => y[1] - x[1]).slice(0, 3);
      const all = (b.items || []).length;
      // the three largest categories; when they are not all of them, say so
      const lead = top.reduce((sum, [, n]) => sum + n, 0) < all ? ", including" : ":";
      return { agent: from, text: `finds ${plural(all, "candidate")}${lead} ${top.map(([c, n]) => `${categoryLabel(c)} ${n}`).join(", ")}` };
    }
    case "verdict": {
      const item = s.items[b.item_id];
      if (!item) return null;
      const label = itemLabel(item);
      const detail = b.reason ? short(b.reason) : undefined;
      if (item.stage === "suggest") return { agent: from, text: `leaves ${label} as a suggestion for a person`, detail };
      if (b.decision === "drop") return { agent: from, text: `leaves ${label} alone: it is used`, detail };
      return { agent: from, text: `decides ${label} is safe to remove`, detail };
    }
    case "blueprint":
      return { agent: from, text: `plans ${plural((b.packages || []).length, "work package")}` };
    case "package_applied":
      return { agent: from, text: `applies ${b.package}${pkg?.goal ? `: ${lower(pkg.goal.replace(/^Apply P\d+: /, ""))}` : ""}` };
    case "test_result":
      return { agent: from, text: b.ok ? `runs ${b.package}'s tests: all pass` : `runs ${b.package}'s tests: ${plural((b.new_failures || []).length, "new failure")}` };
    case "validation": {
      const pr = b.probes;
      if (!pr) return { agent: from, text: `checks ${b.package}: ${b.ok ? "passed" : "failed"}` };
      return pr.same
        ? { agent: from, text: `probes ${b.package} with ${plural(pr.n_cases, "case")}: same behavior before and after` }
        : { agent: from, text: `probes ${b.package}: behavior changed in ${(pr.mismatches || []).length} of ${plural(pr.n_cases, "case")}` };
    }
    case "failure":
      return { agent: from, text: `sends ${b.package} to the Fixer: its ${b.stage} failed` };
    case "repair":
      return { agent: from, text: b.outcome === "repaired" ? `repairs ${b.package}` : `rolls ${b.package} back` };
    case "final_check": {
      const nf = (b.new_failures || []).length;
      return { agent: from, text: `runs the whole suite: ${b.passed} pass (baseline ${b.baseline_passed}), ${nf ? plural(nf, "new failure") : "no new failures"}` };
    }
    case "report":
      return { agent: from, text: "writes CLEANUP_REPORT.md and the pull request text" };
  }
  return null;
}

export function captionFor(e: StudioEvent, s: RunState): Caption | null {
  const p = e.payload || {};
  const agent = e.agent || "manager";
  switch (e.kind) {
    case "run_start":
      return { agent, text: `starts cleaning ${String(p.repo_id || "the project").replace(/^local:/, "")} in ${p.mode || "safe"} mode${p.dry_run ? " (dry run)" : ""}` };
    case "phase_change":
      if (p.to === "DONE") return null;
      return p.back
        ? { agent, text: `steps back to ${PHASE_LABEL[p.to] || p.to}`, detail: p.reason ? short(p.reason) : undefined }
        : { agent, text: `moves on to ${PHASE_LABEL[p.to] || p.to}` };
    case "message":
      return message(e, s);
    case "tool_call": {
      const text = tool(e, s);
      return text ? { agent, text } : null;
    }
    case "decision":
      if (p.revert) return { agent, text: `reverts ${p.revert}` };
      if (p.rule === "package_done") return { agent, text: `${DONE_TEXT[p.status] || p.status} ${p.package}` };
      if (p.rule === "llm_manager") {
        const choice = String(p.choice || "continue").replace("go_back:", "go back to ").replace(/_/g, " ");
        return { agent, text: `decides to ${choice.toLowerCase()}`, detail: p.text ? short(p.text) : undefined };
      }
      return null;
    case "lesson":
      return { agent, text: `writes lesson ${p.lesson_id}`, detail: p.reason ? short(p.reason) : undefined };
    case "check":
      return p.check === "probe coverage" && typeof p.coverage === "number"
        ? { agent, text: `measures probe coverage of ${p.package}: ${Math.round(p.coverage * 100)}% of the changed lines` }
        : null;
    case "run_end": {
      const sm = p.summary || {};
      return { agent, text: `ends the run: ${sm.verdict || "done"}${typeof sm.applied === "number" ? `, ${plural(sm.applied, "edit")} applied` : ""}` };
    }
  }
  return null;
}

// Every captioned step of a run, folding the events once.
export function captionSteps(events: StudioEvent[]): CaptionStep[] {
  const folder = newFolder();
  const out: CaptionStep[] = [];
  events.forEach((e, index) => {
    step(folder, e);
    const c = captionFor(e, folder.state);
    if (c) out.push({ ...c, index, t: e.t, decision: isDecision(e) });
  });
  return out;
}

export function captionText(c: Caption): string {
  return `${agentName(c.agent)} ${c.text}`;
}

// The one sentence over a run screen: what the team is doing and how much slop it has removed.
export function runSentence(s: RunState): string {
  const found = plural(s.candidates, "candidate");
  const removed = `${s.applied} of ${s.candidates} removed`;
  const rolledBack = Object.values(s.items).filter((i) => i.stage === "rolled_back").length;
  const back = rolledBack ? `, ${rolledBack} rolled back` : "";
  if (s.finished || s.phase === "DONE") {
    const how = s.verdict === "everything runs" ? "; everything still runs" : s.verdict ? ` (${s.verdict})` : "";
    return `Done: the team removed ${s.applied} of ${found}${back}${how}.`;
  }
  switch (s.phase) {
    case "BASELINE":
      return "The team is running the project's tests before it changes anything.";
    case "AUDIT":
      return s.candidates ? `The team is looking for slop: ${found} so far.` : "The team is looking for slop.";
    case "INVESTIGATE":
      return `The team is investigating ${found}; ${s.applied} removed so far.`;
    case "PLAN":
      return `The team is planning the edits; ${removed} so far.`;
    case "EXECUTE":
      return `The team is removing slop: ${removed} so far${back}.`;
    case "FINAL_VERIFY":
      return `The team is testing the whole project again; ${removed}${back}.`;
    case "REPORT":
      return `The team is writing its report; ${removed}${back}.`;
  }
  return "The team is reading the project.";
}
