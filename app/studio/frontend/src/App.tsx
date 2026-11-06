import { useEffect, useState } from "react";
import { DarkContext } from "./components/Code";
import { ThemeToggle } from "./components/PresentShell";
import { BeforeAfter } from "./screens/BeforeAfter";
import { Cases } from "./screens/Cases";
import { Compare } from "./screens/Compare";
import { BaselinesScreen, DataScreen, GuardScreen, ReportsScreen, SchedulerScreen } from "./screens/Dashboard";
import { Evaluation } from "./screens/Evaluation";
import { Home } from "./screens/Home";
import { Launcher } from "./screens/Launcher";
import { Present } from "./screens/Present";
import { Results } from "./screens/Results";
import { RunView } from "./screens/RunView";
import { RunsScreen } from "./screens/Runs";
import { Watch } from "./screens/Watch";

type Theme = "light" | "dark";

const NAV: { section: string; links: [string, string][] }[] = [
  {
    section: "Studio",
    links: [
      ["home", "Home"],
      ["runs", "Runs"],
      ["launch", "Launch"],
      ["compare", "Compare"],
      ["cases", "Case studies"],
      ["watch", "Watch"],
      ["results", "Results"],
      ["evaluation", "Evaluation"],
    ],
  },
  {
    section: "Dashboard (v1)",
    links: [
      ["reports", "Saved reports"],
      ["sweeps", "Live sweep and replay"],
      ["scheduler", "Scheduler"],
      ["baselines", "Baselines"],
      ["data", "Data"],
      ["guard", "Guard"],
    ],
  },
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
  const active = ["run", "replay", "after", "present"].includes(route) ? "runs" : route;
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
      screen = <RunView key={`${route}:${q.get("root")}:${q.get("path")}`} root={q.get("root") || ""} path={q.get("path") || ""} live={route === "run"} />;
      break;
    case "after":
      screen = (
        <BeforeAfter key={`${q.get("root")}:${q.get("path")}:${presenting}`} root={q.get("root") || ""} path={q.get("path") || ""} present={presenting} />
      );
      break;
    case "present":
      screen = <Present key={`${q.get("root")}:${q.get("path")}`} root={q.get("root") || ""} path={q.get("path") || ""} live={q.get("live") === "1"} />;
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
      screen = <Evaluation tab={q.get("tab") || ""} onTab={(tab) => go("evaluation", { tab })} />;
      break;
    case "sweeps":
      screen = <RunsScreen kinds={["v1"]} title="Live sweep and replay (v1 runs)" />;
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
    case "guard":
      screen = <GuardScreen />;
      break;
    default:
      screen = <RunsScreen />;
  }
  return (
    <DarkContext.Provider value={theme === "dark"}>
      <ThemeToggle.Provider value={{ dark: theme === "dark", toggle: () => setTheme(theme === "dark" ? "light" : "dark") }}>
        <div className={presenting ? "app present" : "app"}>
          {!presenting && (
            <nav className="sidebar" aria-label="Screens">
              <a className="brand" href="#/home">
                CleanSweep <span>Studio</span>
              </a>
              {NAV.map((group) => (
                <div key={group.section} className="nav-group">
                  <div className="nav-section">{group.section}</div>
                  {group.links.map(([key, label]) => (
                    <a key={key} href={`#/${key}`} className={active === key ? "active" : ""} aria-current={active === key ? "page" : undefined}>
                      {label}
                    </a>
                  ))}
                </div>
              ))}
              <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Switch theme">
                {theme === "dark" ? "☀ Light theme" : "☾ Dark theme"}
              </button>
            </nav>
          )}
          <main className="content">{screen}</main>
        </div>
      </ThemeToggle.Provider>
    </DarkContext.Provider>
  );
}
