import { createContext, useContext, useState } from "react";
import { api, useApi } from "../api";
import { CodeBlock, DiffView } from "./Code";
import { Async, Drawer } from "./common";

interface ArtifactData {
  id: string;
  kind: string;
  text?: string;
  json?: unknown;
  truncated?: boolean;
}

// The run whose cache the artifact links read from.
export const RunContext = createContext<{ root: string; path: string } | null>(null);

export function ArtifactBody({ id }: { id: string }) {
  const run = useContext(RunContext);
  const res = useApi<ArtifactData>(run ? `${run.root}/${run.path}/${id}` : null, () =>
    api("/api/run/artifact", { root: run!.root, path: run!.path, id }),
  );
  return (
    <Async res={res} what="Loading the artifact">
      {(a) =>
        a.json !== undefined ? (
          <CodeBlock code={JSON.stringify(a.json, null, 1)} language="json" />
        ) : a.kind === "diff" ? (
          <DiffView text={a.text || ""} />
        ) : (
          <CodeBlock code={a.text || ""} />
        )
      }
    </Async>
  );
}

export function ArtifactLink({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const kind = id.split(":")[1] || "artifact";
  return (
    <>
      <button className="chip artifact" onClick={() => setOpen(true)} title={id}>
        {kind.replace(/_/g, " ")}
      </button>
      {open && (
        <Drawer title={id} onClose={() => setOpen(false)}>
          <ArtifactBody id={id} />
        </Drawer>
      )}
    </>
  );
}
