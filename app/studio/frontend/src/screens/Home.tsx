import { useState } from "react";
import { afterHash, api, post, runHash, useApi, type Loaded, type RunRow } from "../api";
import { Async, Badge, PageHeader, Status } from "../components/common";
import { useRuns } from "./Runs";

interface Options {
  targets: { key: string; label: string; path: string }[];
  sandboxes: string[];
  sandbox: boolean;
}

const MODES: [string, string, string][] = [
  ["safe", "Safe", "Only deterministic edits, each one verified; anything uncertain is a suggestion."],
  ["thorough", "Thorough", "Also LLM rewrites of near-duplicates, with more probe rounds."],
];

const SANDBOX_HINT: Record<string, string> = {
  auto: "CleanSweep decides where the project's code runs.",
  docker: "The project's tests and probes run inside a Docker container.",
  none: "The project's tests and probes run on this machine. Clean only code you trust.",
};

const RECENT = 6;

function Segmented({
  name,
  value,
  options,
  onChange,
  disabled = [],
}: {
  name: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
  disabled?: string[];
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={name}>
      {options.map(([key, label]) => (
        <label key={key} title={disabled.includes(key) ? "not available in this version" : undefined}>
          <input
            type="radio"
            name={name}
            value={key}
            checked={value === key}
            disabled={disabled.includes(key)}
            onChange={() => onChange(key)}
          />
          {label}
        </label>
      ))}
    </div>
  );
}

function when(mtime: number): string {
  return mtime ? new Date(mtime * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}

// The shipped recording of the demo app's cleanup, or any shipped agent-team recording.
export const DEMO_RUN = "20261102_demo_feature_agentic";

export function demoRun(rows: RunRow[] | null): RunRow | null {
  const shipped = (rows || []).filter((r) => r.root === "replay" && r.kind === "v2" && r.finished);
  return shipped.find((r) => r.path === DEMO_RUN) || shipped[0] || null;
}

function RecentRuns({ runs, demo }: { runs: Loaded<RunRow[]>; demo: RunRow | null }) {
  return (
    <section aria-label="Recent runs">
      <header className="section-head">
        <h3>Recent runs</h3>
        <a href="#/runs">All runs</a>
      </header>
      <Async
        res={runs}
        what="Finding runs"
        empty={(rows) => (rows.some((r) => r.kind === "v2") ? null : "No cleanups yet. Start one above and it shows up here.")}
        emptyAction={demo ? { label: "Try the demo", href: runHash(demo) } : undefined}
      >
        {(rows) => (
          <div className="recent">
            {rows
              .filter((r: RunRow) => r.kind === "v2")
              .slice(0, RECENT)
              .map((r) => (
                <div key={`${r.root}/${r.path}`} className="recent-row" data-run={r.name}>
                  <span className="run-name" title={`${r.root}/${r.path}`}>
                    {r.name} {r.live && <Badge tone="warn">running</Badge>}
                  </span>
                  <span className="run-actions">
                    {r.verdict ? <Status value={r.verdict} /> : <span className="muted">{r.finished ? "finished" : "unfinished"}</span>}
                    {r.live && <a href={runHash(r, "live")}>Follow live</a>}
                    <a href={runHash(r)}>Open</a>
                    {r.finished && <a href={afterHash(r)}>Before / after</a>}
                  </span>
                  <span className="run-meta">
                    {r.target || "?"} · {r.mode || "?"} mode · model {r.model || "none"}
                    {r.root === "replay" ? " · shipped recording" : ` · ${when(r.mtime)}`}
                  </span>
                </div>
              ))}
          </div>
        )}
      </Async>
    </section>
  );
}

export function Home() {
  const options = useApi<Options>("targets", () => api("/api/targets"));
  const runs = useRuns();
  const demo = demoRun(runs.data);
  const [path, setPath] = useState("");
  const [mode, setMode] = useState("safe");
  const [sandbox, setSandbox] = useState("auto");
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sandboxReady = options.data?.sandbox ?? false;
  const choose = (value: string) => {
    setPath(value);
    setError(null);
  };

  const start = async () => {
    if (!path.trim()) {
      setError("Paste the path of a folder first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const job = await post<{ root: string; path: string }>("/api/jobs", {
        kind: "clean",
        target: path.trim(),
        mode,
        sandbox,
        no_llm: offline,
      });
      window.location.hash = runHash(job, "live");
    } catch (err) {
      const text = (err as Error).message;
      setError(text.charAt(0).toUpperCase() + text.slice(1) + (/[.!?]$/.test(text) ? "" : "."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="screen home">
      <PageHeader
        title="Clean a folder"
        description="Paste a Python project's path. CleanSweep cleans a copy, one checked change at a time."
        help="Start here: clean a project of your own (CleanSweep works on a copy, so your folder is never changed), or watch a recorded cleanup of a small demo app first."
        actions={
          demo && (
            <>
              <a className="button" href={`${runHash(demo)}&tour=1`}>
                Take the tour
              </a>
              <a className="button" href={runHash(demo)}>
                Try the demo
              </a>
            </>
          )
        }
      />
      <form
        className="clean-box"
        aria-label="Clean a folder"
        onSubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <div className="path-row">
          <input
            value={path}
            onChange={(e) => choose(e.target.value)}
            placeholder="/path/to/your/project"
            aria-label="Folder to clean"
            spellCheck={false}
            autoComplete="off"
          />
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Starting..." : "Start"}
          </button>
        </div>
        {options.data && options.data.targets.length > 0 && (
          <div className="shortcuts">
            Try it on:{" "}
            {options.data.targets.map((t, i) => (
              <span key={t.key}>
                {i > 0 && " · "}
                <button type="button" className="link" onClick={() => choose(t.path)}>
                  {t.label}
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="clean-options">
          <fieldset>
            <legend>Mode</legend>
            <Segmented name="Mode" value={mode} options={MODES.map(([k, l]) => [k, l])} onChange={setMode} />
            <span className="option-hint">{MODES.find(([k]) => k === mode)?.[2]}</span>
          </fieldset>
          <fieldset>
            <legend>Sandbox</legend>
            <Segmented
              name="Sandbox"
              value={sandbox}
              options={(options.data?.sandboxes || ["auto", "docker", "none"]).map((s) => [s, s.charAt(0).toUpperCase() + s.slice(1)])}
              onChange={setSandbox}
              disabled={sandboxReady ? [] : ["docker"]}
            />
            <span className="option-hint">
              {SANDBOX_HINT[sandbox]}
              {!sandboxReady && options.data && " The Docker sandbox is not in this version yet."}
            </span>
          </fieldset>
          <fieldset>
            <legend>LLM</legend>
            <label className="check">
              <input type="checkbox" checked={offline} onChange={(e) => setOffline(e.target.checked)} /> Offline: the agents decide by rules
            </label>
            <span className="option-hint">Otherwise the LLM in .env is used, if a key is set. More options on the Launch screen.</span>
          </fieldset>
        </div>
        {error && (
          <div className="state error home-error" role="alert">
            {error}
          </div>
        )}
      </form>
      <RecentRuns runs={runs} demo={demo} />
    </div>
  );
}
