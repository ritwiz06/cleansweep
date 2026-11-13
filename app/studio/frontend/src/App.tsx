import { useEffect, useState } from "react";
import { DarkContext } from "./components/Code";
import { Presenting } from "./components/common";
import { ThemeToggle } from "./components/PresentShell";
import { BeforeAfter } from "./screens/BeforeAfter";
import { Cases } from "./screens/Cases";
import { Compare } from "./screens/Compare";
import { ARCHIVE, ArchiveScreen, BaselinesScreen, DataScreen, GuardScreen, ReportsScreen, SchedulerScreen } from "./screens/Dashboard";
import { Evaluation } from "./screens/Evaluation";
import { Home } from "./screens/Home";
import { Launcher } from "./screens/Launcher";
import { Present } from "./screens/Present";
import { Results } from "./screens/Results";
import { RunView } from "./screens/RunView";
import { RunsScreen } from "./screens/Runs";
import { Watch } from "./screens/Watch";

type Theme = "light" | "dark";

const NAV: [string, string][] = [
  ["home", "Home"],
  ["runs", "Runs"],
  ["launch", "Launch"],
  ["compare", "Compare"],
  ["cases", "Case studies"],
  ["watch", "Watch"],
  ["results", "Results"],
  ["evaluation", "Evaluation"],
];

function parseHash(): { route: string; q: URLSearchParams } {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [route, query = ""] = raw.split("?");
  return { route: route || "home", q: new URLSearchParams(query) };
}

function go(route: string, params: Record<string, string>) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  window.location.hash = `#/${route}${q ? `?${q}` : ""}`;
}

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem("studio-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // storage blocked: follow the system
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function App() {
  const [{ route, q }, setLocation] = useState(parseHash);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    const onHash = () => setLocation(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("studio-theme", theme);
    } catch {
      // not saved; the theme still applies
    }
  }, [theme]);
  const active = ["run", "replay", "after", "present"].includes(route) ? "runs" : ARCHIVE.some(([key]) => key === route) ? "archive" : route;
  const presenting = route === "present" || q.get("present") === "1";
  let screen;
  switch (route) {
    case "home":
      screen = <Home />;
      break;
    case "launch":
      screen = <Launcher />;
      break;
    case "run":
    case "replay":
      screen = (
        <RunView
          key={`${route}:${q.get("root")}:${q.get("path")}`}
          root={q.get("root") || ""}
          path={q.get("path") || ""}
          live={route === "run"}
          tour={q.get("tour") === "1"}
        />
      );
      break;
    case "after":
      screen = (
        <BeforeAfter key={`${q.get("root")}:${q.get("path")}:${presenting}`} root={q.get("root") || ""} path={q.get("path") || ""} present={presenting} />
      );
      break;
    case "present":
      screen = (
        <Present
          key={`${q.get("root")}:${q.get("path")}`}
          root={q.get("root") || ""}
          path={q.get("path") || ""}
          live={q.get("live") === "1"}
          view={q.get("view") === "agents" ? "agents" : "project"}
        />
      );
      break;
    case "compare":
      screen = <Compare a={q.get("a") || ""} b={q.get("b") || ""} onChange={(a, b) => go("compare", { a, b })} />;
      break;
    case "cases":
      screen = <Cases name={q.get("name") || ""} onPick={(name) => go("cases", { name })} />;
      break;
    case "watch":
      screen = <Watch root={q.get("root") || ""} path={q.get("path") || ""} onPick={(root, path) => go("watch", { root, path })} />;
      break;
    case "results":
      screen = <Results />;
      break;
    case "evaluation":
      screen = <Evaluation tab={q.get("tab") || ""} onTab={(tab) => go("evaluation", { tab, present: presenting ? "1" : "" })} />;
      break;
    case "sweeps":
      screen = <RunsScreen kinds={["v1"]} title="Live sweep and replay (Phase 1 runs)" />;
      break;
    case "reports":
      screen = <ReportsScreen root={q.get("root") || ""} path={q.get("path") || ""} onPick={(root, path) => go("reports", { root, path })} />;
      break;
    case "scheduler":
      screen = <SchedulerScreen />;
      break;
    case "baselines":
      screen = <BaselinesScreen />;
      break;
    case "data":
      screen = <DataScreen />;
      break;
    case "archive":
      screen = <ArchiveScreen />;
      break;
    case "guard":
      screen = <GuardScreen />;
      break;
    default:
      screen = <RunsScreen />;
  }
  return (
    <DarkContext.Provider value={theme === "dark"}>
      <ThemeToggle.Provider value={{ dark: theme === "dark", toggle: () => setTheme(theme === "dark" ? "light" : "dark") }}>
        <Presenting.Provider value={presenting}>
          <div className={presenting ? "app present" : "app"}>
            {!presenting && (
              <nav className="sidebar" aria-label="Screens">
                <a className="brand" href="#/home">
                  CleanSweep <span>Studio</span>
                </a>
                <div className="nav-group">
                  {NAV.map(([key, label]) => (
                    <a key={key} href={`#/${key}`} className={active === key ? "active" : ""} aria-current={active === key ? "page" : undefined}>
                      {label}
                    </a>
                  ))}
                </div>
                <a href="#/archive" className={`nav-archive ${active === "archive" ? "active" : ""}`} aria-current={active === "archive" ? "page" : undefined}>
                  Phase 1 archive
                </a>
                <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="Switch theme">
                  <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span> {theme === "dark" ? "Light theme" : "Dark theme"}
                </button>
              </nav>
            )}
            <main className="content">{screen}</main>
          </div>
        </Presenting.Provider>
      </ThemeToggle.Provider>
    </DarkContext.Provider>
  );
}
