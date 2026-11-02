// Fold a v1 live-sweep log (app/dashboard/live_runner.py) into the Live sweep screen's state;
// the same rules as cleansweep.runlog.fold.

export const V1_STAGES = ["open", "analyze", "plan", "rank", "batch", "guard", "hidden", "done"];
export const V1_STAGE_LABELS: Record<string, string> = {
  open: "Open",
  analyze: "Analyze",
  plan: "Plan",
  rank: "Rank",
  batch: "Batch",
  guard: "Guard",
  hidden: "Hidden checks",
  done: "Done",
};

export interface V1Event {
  t: number;
  kind: string;
  [key: string]: any;
}

export interface V1State {
  run: Record<string, any>;
  stages: Record<string, string>;
  stageSeconds: Record<string, number>;
  current: string | null;
  currentSince: number;
  items: any[];
  scores: Record<string, number>;
  batches: any[];
  llm: { n: number; start: number; seconds: number | null }[];
  results: any[];
  stats: Record<string, any>;
  hidden: any | null;
  summary: any | null;
  report: string | null;
  error: string | null;
  logs: V1Event[];
  statuses: Record<string, string>;
  testRuns: number;
  linesRemoved: number;
  t: number;
  kept: number;
  rolledBack: number;
}

export function foldV1(events: V1Event[]): V1State {
  const s: V1State = {
    run: {},
    stages: {},
    stageSeconds: {},
    current: null,
    currentSince: 0,
    items: [],
    scores: {},
    batches: [],
    llm: [],
    results: [],
    stats: {},
    hidden: null,
    summary: null,
    report: null,
    error: null,
    logs: [],
    statuses: {},
    testRuns: 0,
    linesRemoved: 0,
    t: 0,
    kept: 0,
    rolledBack: 0,
  };
  for (const e of events) {
    s.t = e.t;
    switch (e.kind) {
      case "run_start":
        s.run = e;
        break;
      case "stage_start":
        s.stages[e.stage] = "running";
        s.current = e.stage;
        s.currentSince = e.t;
        break;
      case "stage_done":
        s.stages[e.stage] = e.skipped ? "skipped" : "done";
        s.stageSeconds[e.stage] = e.seconds ?? 0;
        if (s.current === e.stage) s.current = null;
        if ("items" in e) s.items = e.items;
        if ("scores" in e) s.scores = e.scores;
        if ("results" in e) s.results = e.results;
        if ("stats" in e) s.stats = e.stats;
        if ("hidden" in e) s.hidden = e.hidden;
        if ("summary" in e) s.summary = e.summary;
        if ("report" in e) s.report = e.report;
        break;
      case "guard_baseline":
        s.testRuns = e.test_runs;
        break;
      case "llm_start":
        s.llm.push({ n: e.n, start: e.t, seconds: null });
        break;
      case "llm_end":
        for (const call of s.llm) if (call.n === e.n) call.seconds = e.seconds;
        break;
      case "batch_start":
        s.batches.push({ ...e, start: e.t, result: null });
        break;
      case "batch_result": {
        const card = [...s.batches].reverse().find((b) => b.n === e.n);
        if (card) {
          for (const [k, v] of Object.entries(e)) if (!["kind", "t", "n"].includes(k)) card[k] = v;
          card.end = e.t;
        }
        Object.assign(s.statuses, e.statuses || {});
        s.testRuns = e.test_runs;
        if (e.lines_removed != null) s.linesRemoved = e.lines_removed;
        break;
      }
      case "log":
        s.logs.push(e);
        break;
      case "error":
        s.error = e.message;
        break;
    }
  }
  if (Object.keys(s.stats).length) {
    s.testRuns = s.stats.test_runs ?? s.testRuns;
    s.linesRemoved = s.stats.lines_removed ?? s.linesRemoved;
  }
  if (s.results.length) s.statuses = Object.fromEntries(s.results.map((r) => [r.item_id, r.status]));
  const values = Object.values(s.statuses);
  s.kept = values.filter((v) => v === "kept" || v === "repaired").length;
  s.rolledBack = values.filter((v) => v === "rolled_back").length;
  return s;
}
