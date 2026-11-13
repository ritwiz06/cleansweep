import { useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, useApi } from "../api";
import { AXIS, SeriesKey, TOOLTIP, SegmentCount, nameOf, stackTotal } from "../components/Charts";
import { CodeBlock, DiffView, Md } from "../components/Code";
import { ANIMATE, Async, Badge, Card, Empty, PageHeader, StatsRow, Status, Tabs, seconds } from "../components/common";
import { RunOutcome } from "../components/RunOutcome";
import { categoryLabel } from "../state/annotate";

export const REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)";
const OUTCOMES = ["kept", "repaired", "rolled_back", "skipped"];
// the item states' colors (docs/studio_design.md): repaired is kept, so it takes the kept color
const OUTCOME_COLOR: Record<string, string> = {
  kept: "var(--st-kept)",
  repaired: "var(--st-kept)",
  rolled_back: "var(--st-rolled-back)",
  skipped: "var(--st-untouched)",
};
// "skipped" results are the candidates left as suggestions or dropped
const OUTCOME_LABEL: Record<string, string> = { skipped: "not applied" };
const outcomeName = (o: string) => OUTCOME_LABEL[o] || o.replace("_", " ");

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
          category: categoryLabel(category),
          ...Object.fromEntries(OUTCOMES.map((o) => [o, counts[o] || 0])),
        }));
        // only the outcomes that happened; the axis ends at the largest category
        const shown = OUTCOMES.filter((o) => byCat.some((r) => Number(r[o as keyof typeof r]) > 0));
        const most = Math.max(1, ...byCat.map((r) => OUTCOMES.reduce((sum, o) => sum + Number(r[o as keyof typeof r] || 0), 0)));
        const reviewed = c.review.rows.filter((r) => r.llm_decision);
        const accepted = reviewed.filter((r) => r.llm_decision === "accept").length;
        const decided = reviewed.filter((r) => r.llm_decision !== "unsure").length;
        return (
          <div>
            <h3>
              {c.name} <RunOutcome verdict={s.verdict} kept={s.packages?.kept} rolledBack={s.packages?.rolled_back} lines={s.lines_removed} />
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
                <StatsRow
                  label="Case study numbers"
                  items={[
                    { label: "Tests passing, before → after", value: `${s.tests_before?.passed ?? "-"} → ${s.tests_after?.passed ?? "-"}`, lead: true },
                    { label: "Lines removed", value: s.lines_removed ?? "-" },
                    { label: "Files removed", value: s.files_removed ?? "-" },
                    { label: "Candidates", value: s.candidates ?? "-" },
                    { label: "Test runs", value: s.test_runs ?? "-" },
                    { label: "Time", value: seconds(s.seconds) },
                  ]}
                />
                <p className="stats-note">
                  {c.brief.python_files ?? "-"} Python files · {s.llm_requests ?? "-"} LLM requests
                </p>
                <Card title="Slop by category: what happened to each candidate">
                  {byCat.length ? (
                    <div className="chart">
                      <SeriesKey series={shown.map((o) => ({ name: outcomeName(o), color: OUTCOME_COLOR[o] }))} />
                      <ResponsiveContainer width="100%" height={Math.max(120, byCat.length * 36 + 32)}>
                        <BarChart data={byCat} layout="vertical" margin={{ top: 8, right: 40, bottom: 8, left: 8 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" horizontal={false} />
                          <XAxis type="number" allowDecimals={false} domain={[0, most]} tick={AXIS} />
                          <YAxis type="category" dataKey="category" width={140} tick={AXIS} />
                          <Tooltip contentStyle={TOOLTIP} />
                          {shown.map((o) => (
                            <Bar key={o} dataKey={o} name={outcomeName(o)} stackId="a" fill={OUTCOME_COLOR[o]} stroke="var(--surface)" strokeWidth={1} isAnimationActive={ANIMATE}>
                              <LabelList dataKey={o} content={SegmentCount} />
                              <LabelList valueAccessor={nameOf("category")} content={stackTotal(byCat, "category", shown, o, String, true)} />
                            </Bar>
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
                  <div className="table-wrap" style={{ maxHeight: 520 }} tabIndex={0}>
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
      <PageHeader
        title="Case studies"
        description="Real projects cleaned by the agent team: their tests before and after, what happened to each candidate, and the diff."
        help="Pick a project on the left. The review sheet's verdicts come from an LLM reviewer, blinded to the method; they are LLM-judged."
      />
      <Async
        res={res}
        what="Loading the case studies"
        empty={(rows) => (rows.length ? null : "No case studies yet; they are read from results/raw/case_studies/.")}
        emptyAction={{ label: "Check again", onClick: res.reload }}
      >
        {(rows) => (
          <div className="cases">
            <div className="case-list" aria-label="Case studies">
              {rows.map((r) => (
                <button
                  key={r.name}
                  aria-current={r.name === name ? "true" : undefined}
                  className={`case-card ${r.name === name ? "active" : ""}`}
                  onClick={() => onPick(r.name)}
                >
                  <span className="case-card-head">
                    <b>{r.name}</b>
                    <RunOutcome verdict={r.verdict} kept={r.packages?.kept} rolledBack={r.packages?.rolled_back} lines={r.lines_removed} />
                  </span>
                  <span className="small muted">{r.project}</span>
                  <span className="small case-card-numbers">
                    tests {r.tests_before ?? "-"} → {r.tests_after ?? "-"}
                    {r.reviewed > 0 && ` · LLM reviewer: ${r.accepted} accept, ${r.rejected} reject`}
                  </span>
                </button>
              ))}
            </div>
            <div className="case-main">
              {name ? <CaseView name={name} /> : <Empty action={{ label: `Open ${rows[0].name}`, onClick: () => onPick(rows[0].name) }}>Pick a case study.</Empty>}
            </div>
          </div>
        )}
      </Async>
    </div>
  );
}
