import { useEffect, useState } from "react";
import { api, post, useApi } from "../api";
import { Async, Card, ErrorBox, Status } from "../components/common";
import { CodeBlock } from "../components/Code";

interface Options {
  targets: { key: string; label: string }[];
  methods: string[];
  modes: string[];
  judge_modes: string[];
  watch: boolean;
}

interface Job {
  id: string;
  kind: string;
  target: string;
  root: string;
  path: string;
  status: string;
  exit_code: number | null;
}

type Kind = "clean" | "sweep" | "watch";

function JobLog({ id }: { id: string }) {
  const [text, setText] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<{ text: string }>(`/api/jobs/${id}/log`).then(
        (d) => alive && setText(d.text),
        () => undefined,
      );
    load();
    const timer = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);
  return <CodeBlock code={text || "(no output yet)"} maxHeight={220} />;
}

export function Launcher() {
  const options = useApi<Options>("targets", () => api("/api/targets"));
  const jobs = useApi<Job[]>("jobs", () => api("/api/jobs"));
  const [kind, setKind] = useState<Kind>("clean");
  const [target, setTarget] = useState("toy");
  const [path, setPath] = useState("");
  const [mode, setMode] = useState("safe");
  const [method, setMethod] = useState("cleansweep");
  const [judge, setJudge] = useState("gatekeeper");
  const [model, setModel] = useState("");
  const [noLlm, setNoLlm] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [budget, setBudget] = useState({ llm: "", minutes: "", tests: "" });
  const [watch, setWatch] = useState({ polls: "1", interval: "60", budget_tests: "60" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [logFor, setLogFor] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    const budgetText = Object.entries(budget)
      .filter(([, v]) => v.trim())
      .map(([k, v]) => `${k}=${v.trim()}`)
      .join(",");
    const spec: Record<string, unknown> = {
      kind,
      target: target === "path" ? path.trim() : target,
      mode,
      method,
      judge_mode: judge,
      model: model.trim() || undefined,
      no_llm: noLlm,
      dry_run: dryRun,
      budget: budgetText || undefined,
      ...(kind === "watch" ? watch : {}),
    };
    try {
      const job = await post<Job>("/api/jobs", spec);
      const q = new URLSearchParams({ root: job.root, path: job.path });
      window.location.hash = kind === "watch" ? `#/watch?${q}` : `#/run?${q}`;
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="screen">
      <header className="screen-head">
        <h2>Launch a run</h2>
        <span className="muted">Runs go to Studio's runs folder; the project itself is never changed.</span>
      </header>
      <Async res={options} what="Loading the options">
        {(o) => (
          <div className="grid two">
            <Card title="What to run">
              <form
                className="form"
                onSubmit={(e) => {
                  e.preventDefault();
                  start();
                }}
              >
                <fieldset>
                  <legend>Run</legend>
                  {(
                    [
                      ["clean", "Clean (agent team, v2)"],
                      ["sweep", "Sweep (v1 pipeline)"],
                      ["watch", "Watch a git repository"],
                    ] as [Kind, string][]
                  ).map(([k, label]) => (
                    <label key={k} className="radio">
                      <input type="radio" name="kind" checked={kind === k} onChange={() => setKind(k)} disabled={k === "watch" && !o.watch} />{" "}
                      {label}
                      {k === "watch" && !o.watch && <span className="muted"> (not available yet)</span>}
                    </label>
                  ))}
                </fieldset>
                <label>
                  Target
                  <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Target">
                    {o.targets.map((t) => (
                      <option key={t.key} value={t.key}>
                        {t.label}
                      </option>
                    ))}
                    <option value="path">Another folder...</option>
                  </select>
                </label>
                {target === "path" && (
                  <label>
                    Absolute path
                    <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/path/to/project" aria-label="Absolute path" />
                  </label>
                )}
                {kind !== "sweep" && (
                  <label>
                    Mode
                    <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Mode">
                      {o.modes.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </label>
                )}
                {kind === "sweep" && (
                  <>
                    <label>
                      Method
                      <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label="Method">
                        {o.methods.map((m) => (
                          <option key={m}>{m}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Judge mode
                      <select value={judge} onChange={(e) => setJudge(e.target.value)} aria-label="Judge mode">
                        {o.judge_modes.map((m) => (
                          <option key={m}>{m}</option>
                        ))}
                      </select>
                    </label>
                  </>
                )}
                <label>
                  Model
                  <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="default: VOYAGER_MODEL" aria-label="Model" />
                </label>
                {kind !== "sweep" && (
                  <label className="check">
                    <input type="checkbox" checked={noLlm} onChange={(e) => setNoLlm(e.target.checked)} /> Offline: no LLM, the agents decide by rules
                  </label>
                )}
                {kind === "clean" && (
                  <>
                    <label className="check">
                      <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> Dry run: plan only
                    </label>
                    <fieldset className="row">
                      <legend>Budgets (empty: the config's)</legend>
                      {(["llm", "minutes", "tests"] as const).map((k) => (
                        <label key={k}>
                          {k === "llm" ? "LLM calls" : k === "tests" ? "test runs" : "minutes"}
                          <input
                            type="number"
                            min={1}
                            value={budget[k]}
                            onChange={(e) => setBudget({ ...budget, [k]: e.target.value })}
                            aria-label={`budget ${k}`}
                          />
                        </label>
                      ))}
                    </fieldset>
                  </>
                )}
                {kind === "watch" && (
                  <fieldset className="row">
                    <legend>Watch</legend>
                    <label>
                      polls
                      <input type="number" min={1} value={watch.polls} onChange={(e) => setWatch({ ...watch, polls: e.target.value })} />
                    </label>
                    <label>
                      seconds between
                      <input type="number" min={1} value={watch.interval} onChange={(e) => setWatch({ ...watch, interval: e.target.value })} />
                    </label>
                    <label>
                      test-run budget
                      <input type="number" min={0} value={watch.budget_tests} onChange={(e) => setWatch({ ...watch, budget_tests: e.target.value })} />
                    </label>
                  </fieldset>
                )}
                {error && <ErrorBox error={error} />}
                <button type="submit" className="primary" disabled={busy || (target === "path" && !path.trim())}>
                  {busy ? "Starting..." : "Start"}
                </button>
              </form>
            </Card>
            <Card title="Runs started in this session" actions={<button onClick={jobs.reload}>Refresh</button>}>
              <Async res={jobs} empty={(j) => (j.length ? null : "Nothing started yet.")}>
                {(list) => (
                  <ul className="jobs">
                    {list.map((j) => (
                      <li key={j.id}>
                        <code>{j.id}</code> <Status value={j.status} />{" "}
                        <a href={`#/${j.kind === "watch" ? "watch" : "run"}?${new URLSearchParams({ root: j.root, path: j.path })}`}>open</a>{" "}
                        <button className="link" onClick={() => setLogFor(logFor === j.id ? null : j.id)}>
                          output
                        </button>
                        {j.status === "running" && (
                          <button className="link" onClick={() => post(`/api/jobs/${j.id}/stop`, {}).then(jobs.reload)}>
                            stop
                          </button>
                        )}
                        {logFor === j.id && <JobLog id={j.id} />}
                      </li>
                    ))}
                  </ul>
                )}
              </Async>
            </Card>
          </div>
        )}
      </Async>
    </div>
  );
}
