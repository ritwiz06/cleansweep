import { useState } from "react";
import { api, ApiError, imageUrl, useApi, type Table } from "../api";
import { Md } from "../components/Code";
import { Async, Card, DataTable, Empty, PageHeader, ShowMore, Tabs } from "../components/common";
import { injectionBars, records } from "../state/evaluation";
import { fileTitle } from "../state/names";
import { injectionTakeaway, v3InjectionTakeaway } from "../state/takeaways";

interface Index {
  v1: { tables: string[]; notes: string[]; figures: string[] };
  v2: { tables: string[]; notes: string[]; figures: string[] };
  v3?: { tables: string[]; notes: string[]; figures: string[] };
}

type Version = "v1" | "v2" | "v3";
const HEADLINE: Record<string, string> = { v1: "main_table.csv", v2: "llm_review_acceptance.csv", v3: "hypotheses.csv" };
// the figure each phase opens on: the one its answer rests on
const HEADLINE_FIGURE: Record<string, string> = { v1: "main_lines_removed.png", v3: "injection_recall.png" };
const NO_FILES = { tables: [], notes: [], figures: [] };

// Each phase's answer in one sentence, from the table it rests on.
const ANSWER: Record<string, { table: string; say: (t: Table) => string | null }> = {
  v2: { table: "injection_seeds.csv", say: (t) => injectionTakeaway(injectionBars(records(t))) },
  v3: { table: "injection.csv", say: (t) => v3InjectionTakeaway(records(t)) },
};

export function Figure({ path, caption }: { path: string | null | undefined; caption?: string }) {
  if (!path) return null;
  return (
    <figure className="figure">
      <img src={imageUrl("results", path)} alt={caption || path} loading="lazy" />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

function TableView({ version, name }: { version: string; name: string }) {
  const res = useApi<Table>(`table:${version}/${name}`, () => api("/api/table", { root: "results", path: `summary/${version}/${name}` }));
  return <Async res={res} what={`Loading ${name}`}>{(t) => <DataTable table={t} label={name} maxHeight={520} />}</Async>;
}

function NoteView({ version, name }: { version: string; name: string }) {
  const res = useApi<{ text: string }>(`note:${version}/${name}`, () => api("/api/file", { root: "results", path: `summary/${version}/${name}` }));
  return <Async res={res}>{(d) => <Md text={d.text} />}</Async>;
}

function Answer({ version }: { version: string }) {
  const answer = ANSWER[version];
  const res = useApi<Table | null>(`answer:${version}`, () =>
    answer
      ? api<Table>("/api/table", { root: "results", path: `summary/${version}/${answer.table}` }).catch((err) => {
          if (err instanceof ApiError && err.status === 404) return null;
          throw err;
        })
      : Promise.resolve(null),
  );
  const text = answer && res.data ? answer.say(res.data) : version === "v1" ? "Phase 1 cleaned with one gatekeeper; its tables and figures stay here for the record." : null;
  return text ? <p className="takeaway">{text}</p> : null;
}

export function Results() {
  const res = useApi<Index>("results", () => api("/api/results"));
  // the latest phase first
  const [version, setVersion] = useState<Version>("v3");
  const [table, setTable] = useState<string>("");
  return (
    <div className="screen">
      <PageHeader
        title="Results"
        description="Every committed table and figure, by phase."
        help="From results/summary/ and results/figures/. Each phase opens on its main figure; the other figures and every table open on request (click a column to sort)."
      />
      <Tabs
        tabs={[
          { key: "v1", label: "Phase 1" },
          { key: "v2", label: "Phase 2" },
          { key: "v3", label: "Phase 3" },
        ]}
        value={version}
        onChange={(v) => {
          setVersion(v);
          setTable("");
        }}
      />
      <Async res={res} what="Loading the results index">
        {(index) => {
          const files = index[version] ?? NO_FILES;
          const chosen = table || (files.tables.includes(HEADLINE[version]) ? HEADLINE[version] : files.tables[0]);
          const note = chosen?.replace(/\.csv$/, ".md");
          const main = files.figures.includes(HEADLINE_FIGURE[version]) ? HEADLINE_FIGURE[version] : files.figures[0];
          return (
            <>
              <Answer key={version} version={version} />
              <Card title={main ? fileTitle(main) : "Figures"}>
                {main ? (
                  <div className="main-figure">
                    <Figure path={`figures/${version}/${main}`} />
                  </div>
                ) : (
                  <Empty action={{ label: "Check again", onClick: res.reload }}>No figures for this phase yet; the Evaluation screen charts its tables.</Empty>
                )}
                {files.figures.length > 1 && (
                  <ShowMore label={`Show all ${files.figures.length} figures`}>
                    <div className="gallery">
                      {files.figures.map((f) => (
                        <Figure key={f} path={`figures/${version}/${f}`} caption={fileTitle(f)} />
                      ))}
                    </div>
                  </ShowMore>
                )}
              </Card>
              {chosen ? (
                <ShowMore label={`Show the tables (${files.tables.length})`}>
                  <label className="table-pick">
                    Table{" "}
                    <select value={chosen} onChange={(e) => setTable(e.target.value)} aria-label="Table">
                      {files.tables.map((t) => (
                        <option key={t} value={t}>
                          {fileTitle(t)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <TableView version={version} name={chosen} />
                  {note && files.notes.includes(note) && (
                    <details>
                      <summary>Notes on {fileTitle(chosen)}</summary>
                      <NoteView version={version} name={note} />
                    </details>
                  )}
                </ShowMore>
              ) : (
                <Empty action={{ label: "Check again", onClick: res.reload }}>No tables for this phase yet.</Empty>
              )}
            </>
          );
        }}
      </Async>
    </div>
  );
}
