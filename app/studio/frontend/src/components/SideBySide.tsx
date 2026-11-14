import { Highlight } from "prism-react-renderer";
import { useContext } from "react";
import { sideBySide, type Hunk } from "../state/diff";
import { DarkContext, codeTheme } from "./Code";

// One hunk as a table: the old lines on the left, the new ones on the right, highlighted.
export function SideBySide({ hunk, path, only }: { hunk: Hunk; path: string; only?: "left" | "right" }) {
  const dark = useContext(DarkContext);
  const rows = sideBySide(hunk);
  const theme = codeTheme(dark);
  const language = path.endsWith(".py") ? "python" : "plain";
  const left = rows.filter((r) => r.left).map((r) => r.left!.text).join("\n");
  const right = rows.filter((r) => r.right).map((r) => r.right!.text).join("\n");
  return (
    <Highlight theme={theme} code={left} language={language}>
      {(old) => (
        <Highlight theme={theme} code={right} language={language}>
          {(now) => {
            let a = 0;
            let b = 0;
            return (
              <table className={`sbs ${only ? `only-${only}` : ""}`} aria-label={`${path} ${hunk.header}`}>
                <colgroup>
                  <col className="num" />
                  <col />
                  <col className="num" />
                  <col />
                </colgroup>
                <tbody>
                  {rows.map((r, i) => {
                    const lt = r.left ? old.tokens[a++] : null;
                    const rt = r.right ? now.tokens[b++] : null;
                    return (
                      <tr key={i}>
                        <td className={`num ${r.left?.kind || "empty"}`}>{r.left?.n}</td>
                        <td className={`code ${r.left?.kind || "empty"}`}>
                          {r.left?.kind === "del" && <span className="sr-only">removed: </span>}
                          {lt?.map((token, k) => <span key={k} {...old.getTokenProps({ token })} />)}
                        </td>
                        <td className={`num ${r.right?.kind || "empty"}`}>{r.right?.n}</td>
                        <td className={`code ${r.right?.kind || "empty"}`}>
                          {r.right?.kind === "add" && <span className="sr-only">added: </span>}
                          {rt?.map((token, k) => <span key={k} {...now.getTokenProps({ token })} />)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          }}
        </Highlight>
      )}
    </Highlight>
  );
}
