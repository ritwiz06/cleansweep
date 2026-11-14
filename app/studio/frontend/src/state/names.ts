// What a run, a case study or a results file is called on screen: a name a person reads, with
// the folder or file name kept for the tooltip.

export const KIND_LABEL: Record<string, string> = { v2: "agent team", v1: "Phase 1 sweep", watch: "watch" };

// the shipped demo projects by the names the README and the talk use
const KNOWN: Record<string, string> = { shop_app: "Demo app", toy_repo: "Toy repo", conflict: "Step-back scenario" };

const WORDS: Record<string, string> = { aidev: "AIDev", llm: "LLM", swebench: "SWE-bench", v1: "Phase 1", v2: "Phase 2", v3: "Phase 3", ci: "CI", pr: "PR" };

// "local:shop_app" -> "Demo app"; "aidev:owner/Skill_Seekers@5b5d8df" -> "Skill_Seekers".
export function targetName(target: string | null | undefined): string {
  if (!target) return "";
  const bare = target.replace(/^[a-z]+:/, "").replace(/@.*$/, "").split("/").pop() || target;
  return KNOWN[bare] ?? bare;
}

// "2026-11-02T06:00:32+00:00" -> "Nov 2"; nothing for a missing or unreadable time.
export function shortDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// "Demo app · agent team · Nov 2" (the date only when the run recorded when it started); a watch
// folder named "watch" goes by the folder it sits in ("watch_demo · watch").
export function runTitle(run: { name: string; target: string | null; kind: string; started?: string | null; path?: string }): string {
  const folder = run.kind === "watch" && run.name === "watch" && run.path ? run.path.split("/").slice(-2, -1)[0] : "";
  return [targetName(run.target) || folder || run.name, KIND_LABEL[run.kind] || run.kind, shortDay(run.started)].filter(Boolean).join(" · ");
}

// "main_table.csv" -> "Main table"; "aidev_funnel.png" -> "AIDev funnel".
export function fileTitle(file: string): string {
  const words = file
    .replace(/\.[a-z]+$/, "")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => WORDS[w.toLowerCase()] ?? w);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// A case study's folder name under its project: "skill-seekers-abl-no_research" of
// Skill_Seekers -> "Skill_Seekers · ablation: no research".
export function caseTitle(name: string, project: string | null | undefined): string {
  const base = targetName(project) || name;
  const slug = base.toLowerCase().replace(/_/g, "-");
  const rest = name.toLowerCase().startsWith(slug) ? name.slice(slug.length).replace(/^-/, "") : "";
  if (!rest) return base;
  const variant = rest.replace(/^abl-/, "ablation: ").replace(/[-_]/g, " ");
  return `${base} · ${variant}`;
}

// 2533 -> "42m 13s"; 13.2 -> "13s"; 3725 -> "1h 2m".
export function shortDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const total = Math.round(value);
  if (total < 60) return `${total}s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m` : `${m}m ${s}s`;
}
