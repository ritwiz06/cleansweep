import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, useApi } from "../api";
import { CodeBlock, DiffView, Md } from "../components/Code";
import { ANIMATE, Async, Badge, Card, Empty, Stat, Status, Tabs, seconds } from "../components/common";

export const REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)";
const OUTCOMES = ["kept", "repaired", "rolled_back", "skipped"];
const OUTCOME_COLOR: Record<string, string> = {
  kept: "var(--good)",
  repaired: "var(--info)",
  rolled_back: "var(--bad)",
  skipped: "var(--neutral-mark)",
};
// "skipped" results are the candidates left as suggestions or dropped
const OUTCOME_LABEL: Record<string, string> = { skipped: "not applied" };

interface CaseRow {
  name: string;
  project: string;
  verdict: string;
  seconds: number;
  candidates: number;
  packages: Record<string, number>;
  lines_removed: number;
  files_removed: number;
  tests_before: number | null;
  tests_after: number | null;
  has_review: boolean;
  reviewed: number;
  accepted: number;
  rejected: number;
}

interface CaseDetail {
  name: string;
  summary: Record<string, any>;
  brief: Record<string, any>;
  docs: Record<string, string>;
  has_final_diff: boolean;
  review: { label: string; model: string | null; runs: Record<string, string | null>; rows: Record<string, any>[] };
}

function CaseView({ name }: { name: string }) {
  const res = useApi<CaseDetail>(`case:${name}`, () => api(`/api/cases/${encodeURIComponent(name)}`));
  const [tab, setTab] = useState<"health" | "report" | "review" | "diff">("health");
  const diff = useApi<{ text: string }>(tab === "diff" ? `casediff:${name}` : null, () => api(`/api/cases/${encodeURIComponent(name)}/diff`));
  return (
    <Async res={res} what="Loading the case study">
      {(c) => {
        const s = c.summary;
        const byCat = Object.entries((s.by_category || {}) as Record<string, Record<string, number>>).map(([category, counts]) => ({
          category,
          ...Object.fromEntries(OUTCOMES.map((o) => [o, counts[o] || 0])),
        }));
        const reviewed = c.review.rows.filter((r) => r.llm_decision);
        const accepted = reviewed.filter((r) => r.llm_decision === "accept").length;
        const decided = reviewed.filter((r) => r.llm_decision !== "unsure").length;
        return (
          <div>
            <h3>
              {c.name} <Status value={s.verdict} />
            </h3>
            <p className="muted">{s.project}</p>
            <Tabs
              tabs={[
                { key: "health", label: "Health before / after" },
                { key: "report", label: "Report" },
                { key: "review", label: `Review sheet (${c.review.rows.length})` },
                { key: "diff", label: "Diff" },
              ]}
              value={tab}
              onChange={setTab}
            />
            {tab === "health" && (
              <>
                <div className="stats-row">
                  <Stat label="tests passing before" value={s.tests_before?.passed ?? "-"} />
                  <Stat label="tests passing after" value={s.tests_after?.passed ?? "-"} />
                  <Stat label="Python files" value={c.brief.python_files ?? "-"} />
                  <Stat label="lines removed" value={s.lines_removed ?? "-"} />
                  <Stat label="files removed" value={s.files_removed ?? "-"} />
                  <Stat label="candidates" value={s.candidates ?? "-"} />
                  <Stat label="test runs" value={s.test_runs ?? "-"} />
                  <Stat label="LLM requests" value={s.llm_requests ?? "-"} />
                  <Stat label="time" value={seconds(s.seconds)} />
                </div>
                <Card title="Slop by category: what happened to each candidate">
                  {byCat.length ? (
                    <div className="chart">
                      <ResponsiveContainer width="100%" height={Math.max(160, byCat.length * 34 + 60)}>
                        <BarChart data={byCat} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 24 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
                          <XAxis type="number" allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />
                          <YAxis type="category" dataKey="category" width={130} tick={{ fill: "var(--muted)", fontSize: 12 }} />
                          <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                          <Legend />
                          {OUTCOMES.map((o) => (
                            <Bar key={o} dataKey={o} name={OUTCOME_LABEL[o] || o.replace("_", " ")} stackId="a" fill={OUTCOME_COLOR[o]} isAnimationActive={ANIMATE} />
                          ))}
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <Empty>No candidates by category in this record.</Empty>
                  )}
                </Card>
                {c.docs["diffstat.txt"] && (
                  <Card title="Diff stats">
                    <CodeBlock code={c.docs["diffstat.txt"]} />
                  </Card>
                )}
              </>
            )}
            {tab === "report" &&
              (c.docs["CLEANUP_REPORT.md"] ? <Md text={c.docs["CLEANUP_REPORT.md"]} /> : <Empty>No CLEANUP_REPORT.md in this record.</Empty>)}
            {tab === "review" && (
              <Card title="Review sheet">
                <p className="review-label">
                  <Badge tone="info">{REVIEW_LABEL}</Badge> — an LLM's judgment
                  {c.review.model ? ` (${c.review.model})` : ""}, not a human review. Three votes per row; the majority decides.
                </p>
                {reviewed.length > 0 && (
                  <p>
                    {REVIEW_LABEL}: <b>{decided ? `${Math.round((accepted / decided) * 100)}%` : "-"}</b> ({accepted} accepted of {decided} decided,{" "}
                    {reviewed.length - decided} unsure)
                  </p>
                )}
                {!c.review.rows.length ? (
                  <Empty>No review sheet for this case study.</Empty>
                ) : (
                  <div className="table-wrap" style={{ maxHeight: 520 }}>
                    <table className="data" aria-label="Review sheet">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>mode</th>
                          <th>kind</th>
                          <th>item</th>
                          <th>category</th>
                          <th>what</th>
                          <th>outcome</th>
                          <th>{REVIEW_LABEL}</th>
                          <th>votes</th>
                          <th>reviewer's reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {c.review.rows.map((r) => (
                          <tr key={r.n}>
                            <td>{r.n}</td>
                            <td>{r.mode}</td>
                            <td>{r.kind}</td>
                            <td>
                              <code>{r.item}</code>
                            </td>
                            <td>{r.category}</td>
                            <td className="wrap">{r.what}</td>
                            <td>
                              <Status value={r.outcome} />
                            </td>
                            <td>{r.llm_decision ? <Status value={r.llm_decision} /> : <span className="muted">not reviewed</span>}</td>
                            <td>{(r.llm_votes || []).join(", ")}</td>
                            <td className="wrap">{r.llm_reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}
            {tab === "diff" &&
              (c.has_final_diff ? (
                <Async res={diff} what="Loading the diff">
                  {(d) => <DiffView text={d.text} maxHeight={640} />}
                </Async>
              ) : (
                <Empty>This record has no final.diff (see the report and the diff stats).</Empty>
              ))}
          </div>
        );
      }}
    </Async>
  );
}

export function Cases({ name, onPick }: { name: string; onPick: (name: string) => void }) {
  const res = useApi<CaseRow[]>("cases", () => api("/api/cases"));
  return (
    <div className="screen">
      <header className="screen-head">
        <h2>Case studies</h2>
        <span className="muted">Real projects cleaned by the agent team (results/raw/case_studies/).</span>
      </header>
      <Async res={res} what="Loading the case studies" empty={(rows) => (rows.length ? null : "No case studies in results/raw/case_studies/ yet.")}>
        {(rows) => (
          <div className="cases">
            <div className="case-list">
              {rows.map((r) => (
                <button key={r.name} className={`case-card ${r.name === name ? "active" : ""}`} onClick={() => onPick(r.name)}>
                  <b>{r.name}</b> <Status value={r.verdict} />
                  <span className="small muted">{r.project}</span>
                  <span className="small">
                    tests {r.tests_before ?? "-"} → {r.tests_after ?? "-"} · {r.lines_removed ?? 0} lines removed
                    {r.reviewed > 0 && ` · LLM reviewer: ${r.accepted} accept, ${r.rejected} reject`}
                  </span>
                </button>
              ))}
            </div>
            <div className="case-main">{name ? <CaseView name={name} /> : <Empty>Pick a case study.</Empty>}</div>
          </div>
        )}
      </Async>
    </div>
  );
}
