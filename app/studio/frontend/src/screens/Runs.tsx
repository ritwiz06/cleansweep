import { useState } from "react";
import { afterHash, api, runHash, useApi, type RunRow } from "../api";
import { Async, Badge, PageHeader, Status } from "../components/common";

export const KIND_LABEL: Record<string, string> = { v2: "agent team", v1: "Phase 1 sweep", watch: "watch" };

export function useRuns() {
  return useApi<RunRow[]>("runs", () => api("/api/runs"));
}

export function RunsScreen({ kinds = ["v2", "v1", "watch"], title = "Runs" }: { kinds?: string[]; title?: string }) {
  const runs = useRuns();
  const [root, setRoot] = useState("");
  const [kind, setKind] = useState("");
  return (
    <div className="screen">
      <PageHeader
        title={title}
        description="Every recorded run: the shipped recordings, results/ and the runs started from Studio. Replay works offline."
        help="Each row is one run. Replay plays it back, Before / after shows what it changed, Compare puts two runs side by side."
        actions={<button onClick={runs.reload}>Refresh</button>}
      />
      <div className="filters">
        <label>
          Where{" "}
          <select value={root} onChange={(e) => setRoot(e.target.value)} aria-label="Where">
            <option value="">everywhere</option>
            <option value="replay">shipped recordings (demo/replay)</option>
            <option value="results">results/</option>
            <option value="runs">started from Studio</option>
          </select>
        </label>
        {kinds.length > 1 && (
          <label>
            Kind{" "}
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
              <option value="">all</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <Async
        res={runs}
        what="Finding runs"
        empty={(rows) => (rows.some((r) => kinds.includes(r.kind)) ? null : "No runs yet. Start one and it shows up here.")}
        emptyAction={{ label: "Clean a folder", href: "#/home" }}
      >
        {(rows) => (
          <div className="table-wrap" style={{ maxHeight: "none" }} tabIndex={0}>
            <table className="data runs" aria-label="Runs">
              <thead>
                <tr>
                  <th>run</th>
                  <th>kind</th>
                  <th>where</th>
                  <th>target</th>
                  <th>mode</th>
                  <th>model</th>
                  <th>result</th>
                  <th>open</th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((r) => kinds.includes(r.kind) && (!root || r.root === root) && (!kind || r.kind === kind))
                  .map((r) => (
                    <tr key={`${r.root}/${r.path}`} data-run={r.name}>
                      <td>
                        <code>{r.name}</code>
                        {r.live && <Badge tone="warn">live</Badge>}
                      </td>
                      <td>{KIND_LABEL[r.kind]}</td>
                      <td className="muted">
                        {r.root}/{r.path.split("/").slice(0, -1).join("/")}
                      </td>
                      <td>{r.target || "-"}</td>
                      <td>{r.mode || "-"}</td>
                      <td>{r.model || "-"}</td>
                      <td>{r.verdict ? <Status value={r.verdict} /> : r.finished ? "finished" : <span className="muted">unfinished</span>}</td>
                      <td className="actions">
                        {r.kind === "watch" ? (
                          <a href={`#/watch?${new URLSearchParams({ root: r.root, path: r.path })}`}>Watch</a>
                        ) : (
                          <>
                            <a href={runHash(r)}>Replay</a>
                            {r.kind === "v2" && r.finished && <a href={afterHash(r)}>Before / after</a>}
                            {r.live && <a href={runHash(r, "live")}>Live</a>}
                            <a href={`#/compare?${new URLSearchParams({ a: `${r.root}:${r.path}` })}`}>Compare</a>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </div>
  );
}
