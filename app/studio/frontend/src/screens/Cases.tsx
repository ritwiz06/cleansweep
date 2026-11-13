import { useEffect, useRef, useState } from "react";
import { api, useApi } from "../api";
import { DiffView, Md } from "../components/Code";
import { Async, Badge, Card, Empty, PageHeader, StatsRow, Status, Tabs, seconds } from "../components/common";
import { RunOutcome } from "../components/RunOutcome";
import { categoryLabel } from "../state/annotate";
import { caseTitle, shortDuration } from "../state/names";

export const REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)";
const OUTCOMES = ["kept", "repaired", "rolled_back", "skipped"];

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

// The slop found in each category, largest first, as grey bars with the count at their end; what
// the cleanup kept and rolled back follows each bar in words.
function CategoryBars({ byCategory }: { byCategory: Record<string, Record<string, number>> }) {
  const rows = Object.entries(byCategory)
    .map(([category, counts]) => ({
      name: categoryLabel(category),
      found: OUTCOMES.reduce((sum, o) => sum + (counts[o] || 0), 0),
      kept: (counts.kept || 0) + (counts.repaired || 0),
      rolledBack: counts.rolled_back || 0,
    }))
    .sort((a, b) => b.found - a.found);
  const most = Math.max(1, ...rows.map((r) => r.found));
  return (
    <div className="chart" role="img" aria-label="Slop found by category">
      <div className="chart-title">
        Slop found by category, with what was kept and rolled back <span className="better">(more kept is better)</span>
      </div>
      <ul className="cat-bars">
        {rows.map((r) => (
          <li key={r.name}>
            <span className="cat-name">{r.name}</span>
            <span className="cat-track">
              <span className="cat-bar" style={{ width: `${(r.found / most) * 100}%` }} />
              <span className="cat-value">{r.found} found</span>
            </span>
            <span className="cat-outcome">
              {r.kept > 0 && <span className="good-text">{r.kept} kept</span>}
              {r.rolledBack > 0 && <span>{r.rolledBack} rolled back</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// git's diff stat as a table: each file with its changed lines, and the summary line under it.
function DiffStats({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim());
  const files = lines.filter((l) => l.includes("|")).map((l) => {
    const [path, rest] = l.split("|");
    return { path: path.trim(), changed: Number.parseInt(rest, 10) || 0 };
  });
  const summary = lines.find((l) => !l.includes("|"));
  return (
    <>
      <div className="table-wrap" tabIndex={0}>
        <table className="data" aria-label="Diff stats">
          <thead>
            <tr>
              <th>File</th>
              <th className="num">Lines changed</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.path}>
                <td className="ident">{f.path}</td>
                <td className="num">{f.changed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summary && <p className="muted small">{summary.trim()}</p>}
    </>
  );
}

function CaseView({ name }: { name: string }) {
  const res = useApi<CaseDetail>(`case:${name}`, () => api(`/api/cases/${encodeURIComponent(name)}`));
  const [tab, setTab] = useState<"health" | "report" | "review" | "diff">("health");
  const diff = useApi<{ text: string }>(tab === "diff" ? `casediff:${name}` : null, () => api(`/api/cases/${encodeURIComponent(name)}/diff`));
  return (
    <Async res={res} what="Loading the case study">
      {(c) => {
        const s = c.summary;
        const reviewed = c.review.rows.filter((r) => r.llm_decision);
        const accepted = reviewed.filter((r) => r.llm_decision === "accept").length;
        const decided = reviewed.filter((r) => r.llm_decision !== "unsure").length;
        return (
          <div>
            <h3 title={c.name}>
              {caseTitle(c.name, s.project)}{" "}
              <RunOutcome verdict={s.verdict} kept={s.packages?.kept} rolledBack={s.packages?.rolled_back} lines={s.lines_removed} />
            </h3>
            <p className="muted one-line" title={s.project}>
              {s.project}
            </p>
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
                    { label: "Time", value: shortDuration(s.seconds), hint: seconds(s.seconds) },
                  ]}
                />
                <p className="stats-note">
                  {c.brief.python_files ?? "-"} Python files · {s.llm_requests ?? "-"} LLM requests
                </p>
                <Card title="Slop by category">
                  {Object.keys(s.by_category || {}).length ? <CategoryBars byCategory={s.by_category} /> : <Empty>No candidates by category in this record.</Empty>}
                </Card>
                {c.docs["diffstat.txt"] && (
                  <Card title="Diff stats">
                    <DiffStats text={c.docs["diffstat.txt"]} />
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

// The case studies, the chosen one outlined in the accent and scrolled into view inside the list.
function CaseList({ rows, name, onPick }: { rows: CaseRow[]; name: string; onPick: (name: string) => void }) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = list.current;
    const card = box?.querySelector<HTMLElement>(".case-card.active");
    if (!box || !card) return;
    if (card.offsetTop < box.scrollTop || card.offsetTop + card.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTop = card.offsetTop - box.clientHeight / 2 + card.offsetHeight / 2;
    }
  }, [name, rows.length]);
  return (
    <div className="case-list" aria-label="Case studies" ref={list}>
      {rows.map((r) => (
        <button
          key={r.name}
          title={r.name}
          aria-current={r.name === name ? "true" : undefined}
          className={`case-card ${r.name === name ? "active" : ""}`}
          onClick={() => onPick(r.name)}
        >
          <span className="case-card-head">
            <b>{caseTitle(r.name, r.project)}</b>
            <RunOutcome verdict={r.verdict} kept={r.packages?.kept} rolledBack={r.packages?.rolled_back} lines={r.lines_removed} />
          </span>
          <span className="small muted one-line" title={r.project}>
            {r.project}
          </span>
          <span className="small case-card-numbers">
            tests {r.tests_before ?? "-"} → {r.tests_after ?? "-"}
            {r.reviewed > 0 && ` · LLM reviewer: ${r.accepted} accept, ${r.rejected} reject`}
          </span>
        </button>
      ))}
    </div>
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
            <CaseList rows={rows} name={name} onPick={onPick} />
            <div className="case-main">
              {name ? <CaseView name={name} /> : <Empty action={{ label: `Open ${caseTitle(rows[0].name, rows[0].project)}`, onClick: () => onPick(rows[0].name) }}>Pick a case study.</Empty>}
            </div>
          </div>
        )}
      </Async>
    </div>
  );
}
