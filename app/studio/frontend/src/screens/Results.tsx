import { useState } from "react";
import { api, imageUrl, useApi, type Table } from "../api";
import { Md } from "../components/Code";
import { Async, Card, DataTable, Empty, PageHeader, Tabs } from "../components/common";
import { fileTitle } from "../state/names";

interface Index {
  v1: { tables: string[]; notes: string[]; figures: string[] };
  v2: { tables: string[]; notes: string[]; figures: string[] };
  v3?: { tables: string[]; notes: string[]; figures: string[] };
}

type Version = "v1" | "v2" | "v3";
const HEADLINE: Record<string, string> = { v1: "main_table.csv", v2: "llm_review_acceptance.csv", v3: "hypotheses.csv" };
const NO_FILES = { tables: [], notes: [], figures: [] };

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
        help="From results/summary/ and results/figures/. Pick a table to read it (click a column to sort); its notes are below it. The figures are the ones the report uses."
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
          return (
            <>
              <Card
                title="Tables"
                actions={
                  files.tables.length > 0 && (
                    <select value={chosen} onChange={(e) => setTable(e.target.value)} aria-label="Table">
                      {files.tables.map((t) => (
                        <option key={t} value={t}>
                          {fileTitle(t)}
                        </option>
                      ))}
                    </select>
                  )
                }
              >
                {chosen ? <TableView version={version} name={chosen} /> : <Empty action={{ label: "Check again", onClick: res.reload }}>No tables for this phase yet.</Empty>}
                {note && files.notes.includes(note) && (
                  <details>
                    <summary>Notes on {fileTitle(chosen)}</summary>
                    <NoteView version={version} name={note} />
                  </details>
                )}
              </Card>
              <Card title="Figures">
                {files.figures.length ? (
                  <div className="gallery">
                    {files.figures.map((f) => (
                      <Figure key={f} path={`figures/${version}/${f}`} caption={fileTitle(f)} />
                    ))}
                  </div>
                ) : (
                  <Empty action={{ label: "Check again", onClick: res.reload }}>No figures for this phase yet.</Empty>
                )}
              </Card>
            </>
          );
        }}
      </Async>
    </div>
  );
}
