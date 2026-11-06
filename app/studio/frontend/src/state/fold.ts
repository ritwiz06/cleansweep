// Fold a v2 event log (src/cleansweep/agents/events.py) into what the run screens draw.

export interface StudioEvent {
  v?: number;
  id: string;
  parent?: string | null;
  t: number;
  ts?: string;
  run_id?: string;
  agent: string | null;
  squad?: string | null;
  phase: string | null;
  kind: string;
  recipients: string[];
  artifacts: string[];
  payload: any;
}

export const PHASES = [
  "ONBOARD",
  "BASELINE",
  "AUDIT",
  "INVESTIGATE",
  "PLAN",
  "EXECUTE",
  "FINAL_VERIFY",
  "REPORT",
  "DONE",
];

export const SQUADS: Record<string, string> = {
  manager: "manager",
  explorer: "research",
  auditor: "research",
  investigator: "research",
  planner: "research",
  engineer: "development",
  tester: "development",
  validator: "development",
  fixer: "development",
  reporter: "development",
  solo: "single",
};

export const AGENTS = Object.keys(SQUADS);

export type ItemStage =
  | "candidate"
  | "investigating"
  | "safe"
  | "suggest"
  | "dropped"
  | "in_package"
  | "kept"
  | "rolled_back"
  | "repaired"
  | "skipped";

export const STAGE_LABELS: Record<ItemStage, string> = {
  candidate: "Candidate",
  investigating: "Investigating",
  safe: "Safe",
  suggest: "Suggest",
  dropped: "Dropped",
  in_package: "In package",
  kept: "Kept",
  rolled_back: "Rolled back",
  repaired: "Repaired",
  skipped: "Skipped",
};

export interface PhaseSpan {
  phase: string;
  start: number;
  end: number | null;
  back: boolean;
  reason: string;
}

export interface AgentStats {
  role: string;
  squad: string;
  steps: number;
  llmCalls: number;
  llmOpen: number;
  messages: number;
  seconds: number;
  instances: string[];
  lastT: number | null;
}

export interface Message {
  eventId: string;
  msgId: string;
  type: string;
  sender: string;
  recipients: string[];
  body: any;
  artifacts: string[];
  t: number;
  phase: string | null;
}

export interface Verdict {
  decision: string;
  reason: string;
  evidence: any[];
  lessons: string[];
  confidence: number | null;
  agent: string;
  t: number;
}

export interface Item {
  id: string;
  unit: string;
  category: string;
  lane: string;
  stage: ItemStage;
  verdict: Verdict | null;
  chain: StudioEvent[];
  pkg: string | null;
  history: { t: number; stage: ItemStage }[];
  // the agent instance that acted on it last, and when
  actor: string | null;
  lastT: number;
}

export interface TestResult {
  ok: boolean;
  newFailures: string[];
  stage: string;
  artifacts: string[];
  t: number;
}

export interface Package {
  id: string;
  goal: string;
  items: string[];
  status: string;
  diffs: string[];
  applied: string[];
  notApplied: string[];
  tests: TestResult[];
  validation: any | null;
  coverage: number | null;
  ui: string | null;
  commit: string | null;
  failures: { stage: string; artifacts: string[]; t: number }[];
  repair: { outcome: string; turns?: number } | null;
  log: StudioEvent[];
  start: number | null;
  end: number | null;
}

export interface Decision {
  eventId: string;
  t: number;
  agent: string;
  rule: string;
  text: string;
  choice?: string;
  options?: string[];
  proposed?: string;
  pkg?: string;
  status?: string;
}

export interface Lesson {
  id: string;
  pattern: Record<string, any>;
  reason: string;
  source: any;
  agent: string;
  t: number;
}

export interface RunState {
  runId: string;
  repo: string;
  mode: string;
  model: string | null;
  dryRun: boolean;
  budget: { llm_calls?: number; minutes?: number; test_runs?: number };
  t: number;
  count: number;
  finished: boolean;
  verdict: string | null;
  summary: any | null;
  phase: string | null;
  phases: PhaseSpan[];
  backSteps: number;
  agents: Record<string, AgentStats>;
  active: string | null;
  lastMessage: Message | null;
  messages: Message[];
  items: Record<string, Item>;
  itemOrder: string[];
  packages: Record<string, Package>;
  packageOrder: string[];
  decisions: Decision[];
  lessons: Lesson[];
  thoughts: { agent: string; text: string; t: number }[];
  budgetNotes: { agent: string; text: string; t: number }[];
  errors: { agent: string; text: string; t: number }[];
  baseline: any | null;
  finalCheck: any | null;
  blueprint: string | null;
  testRuns: number;
  llmCalls: number;
  probes: number;
  coverage: number | null;
  candidates: number;
  applied: number;
  // the Explorer's project facts (files, tests, entry points)
  facts: any | null;
  // the items the latest item-related event acted on
  focus: string[];
}

export function roleOf(agent: string | null | undefined): string {
  return (agent || "").split("#")[0];
}

export function emptyState(): RunState {
  return {
    runId: "",
    repo: "",
    mode: "",
    model: null,
    dryRun: false,
    budget: {},
    t: 0,
    count: 0,
    finished: false,
    verdict: null,
    summary: null,
    phase: null,
    phases: [],
    backSteps: 0,
    agents: Object.fromEntries(AGENTS.map((a) => [a, newAgent(a)])),
    active: null,
    lastMessage: null,
    messages: [],
    items: {},
    itemOrder: [],
    packages: {},
    packageOrder: [],
    decisions: [],
    lessons: [],
    thoughts: [],
    budgetNotes: [],
    errors: [],
    baseline: null,
    finalCheck: null,
    blueprint: null,
    testRuns: 0,
    llmCalls: 0,
    probes: 0,
    coverage: null,
    candidates: 0,
    applied: 0,
    facts: null,
    focus: [],
  };
}

function newAgent(role: string): AgentStats {
  return {
    role,
    squad: SQUADS[role] || "other",
    steps: 0,
    llmCalls: 0,
    llmOpen: 0,
    messages: 0,
    seconds: 0,
    instances: [],
    lastT: null,
  };
}

function newPackage(id: string): Package {
  return {
    id,
    goal: "",
    items: [],
    status: "planned",
    diffs: [],
    applied: [],
    notApplied: [],
    tests: [],
    validation: null,
    coverage: null,
    ui: null,
    commit: null,
    failures: [],
    repair: null,
    log: [],
    start: null,
    end: null,
  };
}

const DONE_STAGE: Record<string, ItemStage> = {
  kept: "kept",
  rolled_back: "rolled_back",
  repaired: "repaired",
  skipped: "skipped",
};
const VERDICT_STAGE: Record<string, ItemStage> = { safe: "safe", suggest: "suggest", drop: "dropped" };

// Folding is incremental: fold(events) == events.reduce(step, emptyState()) with `pending`
// carrying each investigator's tool calls until its verdict.
export interface Folder {
  state: RunState;
  pending: Record<string, StudioEvent[]>;
  // the candidates each investigator instance was given
  assigned: Record<string, string[]>;
}

export function newFolder(): Folder {
  return { state: emptyState(), pending: {}, assigned: {} };
}

export function fold(events: StudioEvent[]): RunState {
  const folder = newFolder();
  for (const event of events) step(folder, event);
  return folder.state;
}

function setStage(item: Item, stage: ItemStage, t: number) {
  if (item.stage === stage) return;
  item.stage = stage;
  item.history.push({ t, stage });
}

// Mark items as acted on by an agent now (and as the latest action's focus).
function touch(s: RunState, ids: string[], agent: string | null, t: number) {
  const known = ids.filter((id) => s.items[id]);
  if (!known.length) return;
  for (const id of known) {
    if (agent) s.items[id].actor = agent;
    s.items[id].lastT = t;
  }
  s.focus = known;
}

// The candidate an investigator instance works on, from its first tool call's arguments (the
// events say which instance decided which item only at the verdict).
function claim(folder: Folder, args: any): string | null {
  const s = folder.state;
  const wanted = [args?.name, args?.pattern, args?.path].filter((v) => typeof v === "string");
  if (!wanted.length) return null;
  const taken = new Set(Object.entries(folder.assigned).flatMap(([agent, ids]) => (agent.includes("#") ? ids : [])));
  for (const id of s.itemOrder) {
    const item = s.items[id];
    if (item.stage !== "investigating" || taken.has(id)) continue;
    const [path, rest] = item.unit.split("::");
    const stem = path.split("/").pop()!.replace(/\.py$/, "");
    const name = rest ? rest.split(".").pop()! : stem;
    if (wanted.some((w) => w === name || w === path || w === stem)) return id;
  }
  return null;
}

function pkgOf(s: RunState, id: string): Package {
  if (!s.packages[id]) {
    s.packages[id] = newPackage(id);
    s.packageOrder.push(id);
  }
  return s.packages[id];
}

export function step(folder: Folder, e: StudioEvent): void {
  const s = folder.state;
  const p = e.payload || {};
  const role = roleOf(e.agent);
  const gap = Math.max(e.t - s.t, 0);
  s.t = Math.max(s.t, e.t);
  s.count += 1;
  if (role) {
    const a = s.agents[role] || (s.agents[role] = newAgent(role));
    a.seconds += gap;
    a.lastT = e.t;
    if (e.agent && !a.instances.includes(e.agent)) a.instances.push(e.agent);
    if (e.kind !== "llm_end") s.active = role;
  }
  if (role === "investigator" && e.agent?.includes("#") && e.kind === "tool_call" && !folder.assigned[e.agent]) {
    const id = claim(folder, p.args);
    if (id) folder.assigned[e.agent] = [id];
  }
  if (e.agent && folder.assigned[e.agent] && e.kind !== "message") touch(s, folder.assigned[e.agent], e.agent, e.t);
  switch (e.kind) {
    case "run_start":
      s.runId = e.run_id || "";
      s.repo = p.repo_id || "";
      s.mode = p.mode || "";
      s.model = p.model ?? null;
      s.dryRun = Boolean(p.dry_run);
      s.budget = p.budget || {};
      break;
    case "phase_change": {
      const last = s.phases[s.phases.length - 1];
      if (last && last.end === null) last.end = e.t;
      s.phases.push({ phase: p.to, start: e.t, end: null, back: Boolean(p.back), reason: p.reason || "" });
      if (p.back) s.backSteps += 1;
      s.phase = p.to;
      if (p.to === "DONE") s.phases[s.phases.length - 1].end = e.t;
      break;
    }
    case "message":
      onMessage(folder, e);
      break;
    case "decision":
      // the Manager makes no tool calls: its steps are its decisions
      if (role === "manager") s.agents.manager.steps += 1;
      if (p.rule) {
        s.decisions.push({
          eventId: e.id,
          t: e.t,
          agent: role,
          rule: p.rule,
          text: p.text || "",
          choice: p.choice,
          options: p.options,
          proposed: p.proposed,
          pkg: p.package,
          status: p.status,
        });
        if (p.rule === "package_done" && p.package) {
          const pkg = pkgOf(s, p.package);
          pkg.status = p.status;
          pkg.end = e.t;
          const stage = DONE_STAGE[p.status];
          for (const id of pkg.items) if (stage && s.items[id]) setStage(s.items[id], stage, e.t);
          touch(s, pkg.items, e.agent, e.t);
          if (stage === "kept" || stage === "repaired") s.applied += pkg.applied.length || pkg.items.length;
        }
      }
      if (p.revert) {
        // the Engineer undoes a kept package after a worse FINAL VERIFY
        const pkg = pkgOf(s, p.revert);
        if (pkg.status === "kept" || pkg.status === "repaired") s.applied -= pkg.applied.length || pkg.items.length;
        pkg.status = "reverted";
        pkg.end = e.t;
        for (const id of pkg.items) if (s.items[id]) setStage(s.items[id], "rolled_back", e.t);
        touch(s, pkg.items, e.agent, e.t);
      }
      break;
    case "check":
      if (p.package) {
        const pkg = pkgOf(s, p.package);
        if (p.check === "probe coverage") {
          pkg.coverage = p.coverage ?? null;
          s.coverage = p.coverage ?? s.coverage;
        } else if (p.check === "ui") {
          pkg.ui = p.result ?? p.status ?? JSON.stringify(p);
        }
        pkg.log.push(e);
        touch(s, pkg.items, e.agent, e.t);
      }
      break;
    case "tool_call":
    case "tool_result":
      if (e.kind === "tool_call") {
        if (role) s.agents[role].steps += 1;
        if (p.tool === "run_tests") s.testRuns += 1;
      }
      if (role === "investigator" && e.agent) {
        (folder.pending[e.agent] = folder.pending[e.agent] || []).push(e);
      }
      if (p.package) {
        const pkg = pkgOf(s, p.package);
        pkg.log.push(e);
        if (p.tool === "commit" && p.commit) pkg.commit = p.commit;
      }
      if (p.tool === "project_facts" && e.kind === "tool_result" && !s.facts) s.facts = p.result || null;
      {
        const item = p.args?.item || p.item;
        if (typeof item === "string") touch(s, [item], e.agent, e.t);
      }
      break;
    case "llm_start":
      s.llmCalls += 1;
      if (role) {
        s.agents[role].llmCalls += 1;
        s.agents[role].llmOpen += 1;
      }
      break;
    case "llm_end":
      if (role) s.agents[role].llmOpen = Math.max(s.agents[role].llmOpen - 1, 0);
      break;
    case "thought":
      s.thoughts.push({ agent: e.agent || "", text: p.text || "", t: e.t });
      if (s.thoughts.length > 200) s.thoughts.shift();
      break;
    case "budget":
      s.budgetNotes.push({ agent: e.agent || "", text: p.exhausted || JSON.stringify(p), t: e.t });
      break;
    case "lesson":
      s.lessons.push({
        id: p.lesson_id,
        pattern: p.pattern || {},
        reason: p.reason || "",
        source: p.source,
        agent: e.agent || "",
        t: e.t,
      });
      break;
    case "log":
      if (p.level === "ERROR") s.errors.push({ agent: e.agent || "", text: p.message || "", t: e.t });
      break;
    case "run_end":
      s.finished = true;
      s.summary = p.summary || null;
      s.verdict = p.summary?.verdict ?? null;
      if (typeof p.summary?.applied === "number") s.applied = p.summary.applied;
      if (typeof p.summary?.test_runs === "number") s.testRuns = p.summary.test_runs;
      break;
  }
}

function onMessage(folder: Folder, e: StudioEvent) {
  const s = folder.state;
  const p = e.payload || {};
  const body = p.body || {};
  const role = roleOf(e.agent);
  const msg: Message = {
    eventId: e.id,
    msgId: p.msg_id,
    type: p.type,
    sender: e.agent || "",
    recipients: e.recipients || [],
    body,
    artifacts: e.artifacts || [],
    t: e.t,
    phase: e.phase,
  };
  s.messages.push(msg);
  s.lastMessage = msg;
  if (role) s.agents[role].messages += 1;
  const to = roleOf(msg.recipients[0]);
  switch (p.type) {
    case "brief":
      break;
    case "baseline":
      s.baseline = { ...body, artifacts: msg.artifacts };
      break;
    case "candidates":
      for (const c of body.items || []) {
        if (!s.items[c.item_id]) s.itemOrder.push(c.item_id);
        s.items[c.item_id] = {
          id: c.item_id,
          unit: c.unit,
          category: c.category,
          lane: c.lane,
          stage: "candidate",
          verdict: null,
          chain: [],
          pkg: null,
          history: [{ t: e.t, stage: "candidate" }],
          actor: msg.sender || null,
          lastT: e.t,
        };
      }
      s.candidates = s.itemOrder.length;
      s.focus = (body.items || []).map((c: any) => c.item_id);
      break;
    case "task":
      if (to === "investigator") {
        for (const id of body.items || []) if (s.items[id]) setStage(s.items[id], "investigating", e.t);
        if (msg.recipients[0]?.includes("#")) folder.assigned[msg.recipients[0]] = body.items || [];
        touch(s, body.items || [], msg.recipients[0] || null, e.t);
      } else if (to === "engineer" && body.package) {
        const pkg = pkgOf(s, body.package);
        if (body.goal && !pkg.goal) pkg.goal = body.goal;
        if (pkg.start === null) pkg.start = e.t;
        if (body.items?.length) {
          pkg.items = body.items;
          pkg.status = "applying";
          for (const id of body.items) {
            const item = s.items[id];
            if (item) {
              item.pkg = body.package;
              setStage(item, "in_package", e.t);
            }
          }
          touch(s, body.items, msg.recipients[0] || "engineer", e.t);
        }
      }
      break;
    case "verdict": {
      const item = s.items[body.item_id];
      if (!item) break;
      item.verdict = {
        decision: body.decision,
        reason: body.reason || "",
        evidence: body.evidence || [],
        lessons: body.lessons_cited || [],
        confidence: body.confidence ?? null,
        agent: msg.sender,
        t: e.t,
      };
      item.chain = folder.pending[msg.sender] || [];
      folder.pending[msg.sender] = [];
      // a safe verdict keeps a suggest-lane item a suggestion, except a duplicate or wrapper in
      // thorough mode (docs/agentic_design.md, section 15)
      const lifted = s.mode === "thorough" && ["duplicate", "wrapper"].includes(item.category);
      const held = body.decision === "safe" && item.lane && item.lane !== "safe" && !lifted;
      const stage = held ? "suggest" : VERDICT_STAGE[body.decision];
      setStage(item, stage || "suggest", e.t);
      touch(s, [item.id], msg.sender, e.t);
      delete folder.assigned[msg.sender];
      break;
    }
    case "blueprint":
      s.blueprint = msg.artifacts[0] || null;
      for (const id of body.packages || []) pkgOf(s, id);
      break;
    case "package_applied": {
      const pkg = pkgOf(s, body.package);
      pkg.applied = body.applied || [];
      pkg.notApplied = body.not_applied || [];
      pkg.diffs.push(...msg.artifacts);
      pkg.status = "testing";
      touch(s, pkg.items, msg.sender, e.t);
      break;
    }
    case "test_result": {
      s.testRuns += 1;
      const pkg = pkgOf(s, body.package);
      pkg.tests.push({
        ok: Boolean(body.ok),
        newFailures: body.new_failures || [],
        stage: body.stage || "tests",
        artifacts: msg.artifacts,
        t: e.t,
      });
      pkg.status = body.ok ? "validating" : "failing";
      touch(s, pkg.items, msg.sender, e.t);
      break;
    }
    case "validation": {
      const pkg = pkgOf(s, body.package);
      pkg.validation = body;
      if (body.probes?.n_cases) s.probes += body.probes.n_cases;
      if (typeof body.coverage === "number") {
        pkg.coverage = body.coverage;
        s.coverage = body.coverage;
      }
      if (body.checks?.ui) pkg.ui = String(body.checks.ui);
      pkg.status = body.ok ? "committing" : "failing";
      touch(s, pkg.items, msg.sender, e.t);
      break;
    }
    case "failure": {
      const pkg = pkgOf(s, body.package);
      pkg.failures.push({ stage: body.stage, artifacts: msg.artifacts, t: e.t });
      pkg.status = "repairing";
      touch(s, pkg.items, msg.recipients[0] || "fixer", e.t);
      break;
    }
    case "repair": {
      const pkg = pkgOf(s, body.package);
      pkg.repair = { outcome: body.outcome, turns: body.turns };
      touch(s, pkg.items, msg.sender, e.t);
      break;
    }
    case "final_check":
      s.testRuns += 1;
      s.finalCheck = { ...body, artifacts: msg.artifacts };
      break;
  }
}

// Probe mismatches read "target [case]: before X, after Y".
export function parseMismatch(text: string): { target: string; case: string; before: string; after: string } {
  const m = /^(.*) \[([^\]]*)\]: before (.*), after (.*)$/s.exec(text);
  if (!m) return { target: text, case: "", before: "", after: "" };
  return { target: m[1], case: m[2], before: m[3], after: m[4] };
}

export function itemsByStage(s: RunState): Record<ItemStage, Item[]> {
  const out = Object.fromEntries(Object.keys(STAGE_LABELS).map((k) => [k, []])) as unknown as Record<
    ItemStage,
    Item[]
  >;
  for (const id of s.itemOrder) out[s.items[id].stage].push(s.items[id]);
  return out;
}

export function phaseSeconds(s: RunState): Record<string, number> {
  const out: Record<string, number> = {};
  for (const span of s.phases) {
    const end = span.end ?? s.t;
    out[span.phase] = (out[span.phase] || 0) + Math.max(end - span.start, 0);
  }
  return out;
}
