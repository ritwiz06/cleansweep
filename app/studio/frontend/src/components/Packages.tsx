import { useContext, useState } from "react";
import { api, useApi, type RunDetail } from "../api";
import { parseMismatch, type Package, type RunState } from "../state/fold";
import { plural } from "../state/labels";
import { ArtifactBody, ArtifactLink, RunContext } from "./Artifact";
import { DiffView, Md } from "./Code";
import { Async, Badge, Card, Empty, Status, percent } from "./common";

export function DocFile({ root, path, name }: { root: string; path: string; name: string }) {
  const res = useApi<{ text: string }>(`${root}/${path}/${name}`, () => api("/api/file", { root, path: `${path}/${name}` }));
  return (
    <Async res={res} what={`Loading ${name}`}>
      {(d) => (name.endsWith(".md") ? <Md text={d.text} /> : <DiffView text={d.text} />)}
    </Async>
  );
}

function ProbeTable({ probes }: { probes: any }) {
  if (!probes) return <p className="muted">No probes ran for this package.</p>;
  const rows = (probes.mismatches || []).map((m: string) => parseMismatch(m));
  return (
    <div>
      <p>
        {plural(probes.n_cases, "probe case")}, {probes.n_unstable || 0} unstable:{" "}
        {probes.same ? <Badge tone="good">same behavior before and after</Badge> : <Badge tone="bad">{rows.length} differ</Badge>}
      </p>
      {rows.length > 0 && (
        <div className="table-wrap" tabIndex={0}>
          <table className="data" aria-label="Probe results before and after">
            <thead>
              <tr>
                <th>target</th>
                <th>case</th>
                <th>before</th>
                <th>after</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: ReturnType<typeof parseMismatch>, i: number) => (
                <tr key={i}>
                  <td>
                    <code>{r.target}</code>
                  </td>
                  <td>{r.case}</td>
                  <td>
                    <code>{r.before}</code>
                  </td>
                  <td>
                    <code>{r.after}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PackageDetail({ pkg, state, detail }: { pkg: Package; state: RunState; detail: RunDetail | null }) {
  const fallback = (detail?.report?.results || []).filter((r) => pkg.items.includes(r.item_id) && r.diff);
  return (
    <div className="package-detail">
      <h3>
        {pkg.id} <Status value={pkg.status} />
      </h3>
      <p>{pkg.goal}</p>
      <ul className="units">
        {pkg.items.map((id) => (
          <li key={id}>
            <code>{state.items[id]?.unit || id}</code> <span className="muted">{state.items[id]?.category}</span>
          </li>
        ))}
      </ul>
      <Card title="Diff">
        {pkg.diffs.length && detail?.has_cache ? (
          pkg.diffs.map((id) => <ArtifactBody key={id} id={id} />)
        ) : fallback.length ? (
          fallback.map((r) => <DiffView key={r.item_id} text={r.diff} />)
        ) : (
          <Empty>{pkg.status === "planned" ? "Not applied yet." : "No diff in this recording."}</Empty>
        )}
      </Card>
      <PackageChecks pkg={pkg} />
    </div>
  );
}

// A package's tests, checks and probes, as the events report them.
export function PackageChecks({ pkg }: { pkg: Package }) {
  const run = useContext(RunContext);
  const checks = pkg.validation?.checks || {};
  const testLog = pkg.log.filter((e) => e.payload?.tool === "run_tests" || e.kind === "check");
  return (
    <>
      <div className="grid two">
        <Card title="Tests">
          {pkg.tests.length ? (
            <ul className="tests">
              {pkg.tests.map((t, i) => (
                <li key={i}>
                  {t.ok ? <Badge tone="good">pass</Badge> : <Badge tone="bad">fail</Badge>} {t.stage}
                  {t.newFailures.length > 0 && <>: new failures {t.newFailures.join(", ")}</>}{" "}
                  {run && t.artifacts.map((a) => <ArtifactLink key={a} id={a} />)}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No test run yet.</Empty>
          )}
          {testLog.map((e) => (
            <div key={e.id} className="muted small">
              {e.t.toFixed(1)} s {e.kind} {JSON.stringify(e.payload).slice(0, 200)}
            </div>
          ))}
        </Card>
        <Card title="Checks">
          <dl className="facts">
            <dt>Probe coverage</dt>
            <dd>{percent(pkg.coverage)}</dd>
            <dt>UI check</dt>
            <dd>{pkg.ui || checks.ui || <span className="muted">not run</span>}</dd>
            <dt>Public API removed</dt>
            <dd>{(checks.public_api_removed || []).join(", ") || "none"}</dd>
            <dt>Probe note</dt>
            <dd>{checks.probe_note || "-"}</dd>
            <dt>Commit</dt>
            <dd>{pkg.commit ? <code>{pkg.commit.slice(0, 12)}</code> : <span className="muted">none</span>}</dd>
            {pkg.failures.length > 0 && (
              <>
                <dt>Failed at</dt>
                <dd>
                  {pkg.failures.map((f, i) => (
                    <span key={i}>
                      {f.stage} {run && f.artifacts.map((a) => <ArtifactLink key={a} id={a} />)}
                    </span>
                  ))}
                </dd>
              </>
            )}
            {pkg.repair && (
              <>
                <dt>Fixer</dt>
                <dd>
                  {pkg.repair.outcome}
                  {pkg.repair.turns !== undefined && ` after ${pkg.repair.turns} turns`}
                </dd>
              </>
            )}
          </dl>
        </Card>
      </div>
      <Card title="Probes: before vs. after">
        <ProbeTable probes={pkg.validation?.probes} />
      </Card>
    </>
  );
}

export function Packages({ state, detail }: { state: RunState; detail: RunDetail | null }) {
  const run = useContext(RunContext);
  const [chosen, setChosen] = useState<string | null>(null);
  const [showBlueprint, setShowBlueprint] = useState(false);
  const id = chosen && state.packages[chosen] ? chosen : state.packageOrder[0];
  return (
    <div className="packages">
      <div className="package-list">
        <button className={`link ${showBlueprint ? "active" : ""}`} onClick={() => setShowBlueprint(!showBlueprint)}>
          {showBlueprint ? "Hide" : "Show"} blueprint.md
        </button>
        {!state.packageOrder.length && <Empty>No work packages yet; the Planner writes them in PLAN.</Empty>}
        {state.packageOrder.map((p) => (
          <button key={p} className={`package-row ${p === id ? "active" : ""}`} onClick={() => setChosen(p)}>
            <b>{p}</b> <Status value={state.packages[p].status} />
            <span className="goal">{state.packages[p].goal || `${state.packages[p].items.length} items`}</span>
          </button>
        ))}
      </div>
      <div className="package-main">
        {showBlueprint &&
          run &&
          (detail?.docs.includes("blueprint.md") ? (
            <Card title="blueprint.md">
              <DocFile root={run.root} path={run.path} name="blueprint.md" />
            </Card>
          ) : state.blueprint && detail?.has_cache ? (
            <Card title="Blueprint">
              <ArtifactBody id={state.blueprint} />
            </Card>
          ) : (
            <Empty>No blueprint yet.</Empty>
          ))}
        {id && <PackageDetail pkg={state.packages[id]} state={state} detail={detail} />}
      </div>
    </div>
  );
}
