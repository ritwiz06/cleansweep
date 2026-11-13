import { Highlight, themes, type PrismTheme } from "prism-react-renderer";
import { createContext, useContext, useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { parseDiff, type DiffFile } from "../state/diff";
import { Empty } from "./common";

export const DarkContext = createContext(false);
const MAX_LINES = 4000;

// The GitHub and VS Code themes, with the colors that fell under 4.5:1 darkened (light) or
// lightened (dark), measured on the surface and on the red and green diff lines.
const LIGHT: PrismTheme = {
  plain: { color: "#24292f", backgroundColor: "transparent" },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "#5c6670", fontStyle: "italic" } },
    { types: ["string", "attr-value"], style: { color: "#a3114f" } },
    { types: ["punctuation", "operator"], style: { color: "#24292f" } },
    { types: ["entity", "url", "symbol", "number", "boolean", "variable", "constant", "property", "regex", "inserted"], style: { color: "#0b6b6b" } },
    { types: ["atrule", "attr-name", "selector"], style: { color: "#0a5c86" } },
    { types: ["function", "deleted", "tag"], style: { color: "#b31d28" } },
    { types: ["function-variable"], style: { color: "#6f42c1" } },
    { types: ["tag", "selector", "keyword"], style: { color: "#00009f" } },
  ],
};

const DARK: PrismTheme = {
  ...themes.vsDark,
  plain: { ...themes.vsDark.plain, backgroundColor: "transparent" },
  styles: [
    ...themes.vsDark.styles,
    { types: ["prolog"], style: { color: "#8a8a8a" } },
    { types: ["comment"], style: { color: "#7fae6a" } },
    { types: ["constant"], style: { color: "#a3a6dc" } },
    { types: ["char"], style: { color: "#e07a7a" } },
  ],
};

export function codeTheme(dark: boolean): PrismTheme {
  return dark ? DARK : LIGHT;
}

function languageOf(path: string): string {
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".json")) return "json";
  if (/\.(js|jsx|ts|tsx)$/.test(path)) return "javascript";
  if (path.endsWith(".sql")) return "sql";
  return "plain";
}

export function CodeBlock({ code, language = "plain", maxHeight = 480 }: { code: string; language?: string; maxHeight?: number }) {
  const dark = useContext(DarkContext);
  const lines = code.split("\n");
  const shown = lines.length > MAX_LINES ? lines.slice(0, MAX_LINES).join("\n") : code;
  return (
    <div className="code" style={{ maxHeight }} tabIndex={0}>
      <Highlight theme={codeTheme(dark)} code={shown} language={language}>
        {({ tokens, getLineProps, getTokenProps }) => (
          <pre>
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })}>
                {line.map((token, k) => (
                  <span key={k} {...getTokenProps({ token })} />
                ))}
              </div>
            ))}
          </pre>
        )}
      </Highlight>
      {lines.length > MAX_LINES && <div className="muted small">{lines.length - MAX_LINES} more lines not shown</div>}
    </div>
  );
}

// The part of a diff that changes one file (the whole diff if no file matches).
export function filterDiff(text: string, path: string): string {
  const files = parseDiff(text);
  const hit = files.filter((f) => f.path === path);
  return (hit.length ? hit : files).map((f) => [...f.header, ...f.lines].join("\n")).join("\n");
}

function DiffFileView({ file }: { file: DiffFile }) {
  const dark = useContext(DarkContext);
  const [open, setOpen] = useState(true);
  const lines = file.lines.slice(0, MAX_LINES);
  // highlight the code of every line in one pass, then put each line's +/- sign back
  const code = lines.map((l) => (l.startsWith("@@") ? "" : l.slice(1))).join("\n");
  return (
    <div className="diff-file">
      <button className="diff-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{open ? "▾" : "▸"}</span> <code>{file.path}</code>
        <span className="added">+{file.added}</span>
        <span className="removed">-{file.removed}</span>
      </button>
      {open && (
        <Highlight theme={codeTheme(dark)} code={code} language={languageOf(file.path)}>
          {({ tokens, getTokenProps }) => (
            <pre className="diff-body">
              {tokens.map((tokLine, i) => {
                const raw = lines[i] ?? "";
                const kind = raw.startsWith("@@") ? "hunk" : raw[0] === "+" ? "add" : raw[0] === "-" ? "del" : "ctx";
                return (
                  <div key={i} className={`diff-line ${kind}`}>
                    <span className="sign">{kind === "hunk" ? "" : raw[0] || " "}</span>
                    {kind === "hunk" ? (
                      <span>{raw}</span>
                    ) : (
                      tokLine.map((token, k) => <span key={k} {...getTokenProps({ token })} />)
                    )}
                  </div>
                );
              })}
            </pre>
          )}
        </Highlight>
      )}
      {file.lines.length > MAX_LINES && <div className="muted small">{file.lines.length - MAX_LINES} more lines not shown</div>}
    </div>
  );
}

export function DiffView({ text, maxHeight = 560 }: { text: string; maxHeight?: number }) {
  const files = useMemo(() => parseDiff(text || ""), [text]);
  if (!files.length) return <Empty>No changes.</Empty>;
  return (
    <div className="diff" style={{ maxHeight }}>
      {files.map((f, i) => (
        <DiffFileView key={`${f.path}-${i}`} file={f} />
      ))}
    </div>
  );
}

export function Md({ text }: { text: string }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
}
