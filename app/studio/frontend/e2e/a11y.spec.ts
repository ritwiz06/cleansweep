import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// axe-core on every screen, in both themes: no serious or critical violations.
const DEMO = "20261102_demo_feature_agentic";
const Q = `root=replay&path=${DEMO}`;

const SCREENS: [string, string][] = [
  ["home", "home"],
  ["runs", "runs"],
  ["launch", "launch"],
  ["live run", `run?${Q}`],
  ["replay: project", `replay?${Q}`],
  ["replay: agents", `replay?${Q}`],
  ["replay: report", `replay?${Q}`],
  ["before / after", `after?${Q}`],
  ["compare", `compare?a=replay:20261101_toy_clean_offline&b=replay:${DEMO}`],
  ["case studies", "cases?name=proj_a"],
  ["watch", "watch?root=results&path=raw/watch_a"],
  ["results", "results"],
  ["evaluation", "evaluation"],
  ["evaluation: diff audit", "evaluation?tab=audit"],
  ["evaluation: Phase 3 injection", "evaluation?tab=v3-injection"],
  ["evaluation: presented", "evaluation?present=1"],
  ["Phase 1 archive", "archive"],
  ["saved reports", "reports?root=replay&path=20261030_demo_feature_advisory_v1/report.json"],
  ["present", `present?${Q}`],
  ["present: agents", `present?${Q}&view=agents`],
  ["present: before / after", `after?${Q}&present=1`],
];

async function serious(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => {
      const examples = v.nodes.slice(0, 3).map((n) => `${n.target.join(" ")}: ${n.failureSummary?.split("\n").slice(1).join(" ")}`);
      return `${v.id} (${v.impact}), ${v.nodes.length} nodes: ${examples.join(" | ")}`;
    });
}

async function ready(page: Page, route: string, label: string) {
  await page.goto(`/#/${route}`);
  await expect(page.locator("main h2").first()).toBeVisible();
  await expect(page.locator(".state.loading")).toHaveCount(0);
  if (label.startsWith("replay")) {
    await page.getByRole("slider", { name: "Scrubber" }).focus();
    for (let i = 0; i < 20; i++) await page.keyboard.press("PageDown");
  }
  if (label === "replay: agents") await page.getByRole("tab", { name: "Agents" }).click();
  if (label === "replay: report") {
    await page.getByRole("tab", { name: "Report" }).click();
    for (const more of ["message board", "items", "work packages"]) await page.getByText(new RegExp(`^Show the ${more}`)).click();
  }
  if (label.startsWith("present")) await page.keyboard.press("Space");
}

for (const theme of ["light", "dark"]) {
  test(`axe: every screen in the ${theme} theme`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript((t) => localStorage.setItem("studio-theme", t), theme);
    const found: string[] = [];
    for (const [label, route] of SCREENS) {
      await ready(page, route, label);
      found.push(...(await serious(page)).map((v) => `${label}: ${v}`));
    }
    expect(found).toEqual([]);
  });

  test(`axe: the tour and a help popover in the ${theme} theme`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript((t) => localStorage.setItem("studio-theme", t), theme);
    await page.goto(`/#/replay?${Q}&tour=1`);
    await expect(page.getByRole("dialog")).toContainText("Step 1 of");
    expect(await serious(page)).toEqual([]);
    await page.goto("/#/home");
    await page.getByRole("button", { name: "What am I looking at?" }).click();
    await expect(page.getByRole("note")).toBeVisible();
    expect(await serious(page)).toEqual([]);
  });
}

// The screens speak of phases, not versions: a "v1", "v2", "v3" or "v2.1" shows only inside a
// path or file name.
const VERSION_TOKEN = /\bv[123](\.[0-9]+)*\b/g;
const EVAL_TABS = ["injection", "ablations", "audit", "probes", "manager", "reviewer", "watch", "v3-hypotheses", "v3-injection", "v3-real", "v3-audit", "v3-autonomy"];
const MORE_ROUTES = ["sweeps", "scheduler", "baselines", "data", "guard", "archive"];

function versionTokens(text: string): string[] {
  const found: string[] = [];
  for (const word of text.split(/\s+/)) {
    const path = /[/\\]/.test(word) || /\.(py|csv|json|png|md)\W*$/.test(word);
    if (!path) found.push(...(word.match(VERSION_TOKEN) ?? []));
  }
  return found;
}

// opens every "Show ..." line, nested ones too
async function openAll(page: Page) {
  const closed = page.locator("details.show-more:not([open]) > summary");
  for (let i = 0; i < 40 && (await closed.count()) > 0; i++) await closed.first().click();
  await expect(page.locator(".state.loading")).toHaveCount(0);
}

test("no screen, Evaluation tab, Results tab, tour or help text shows a version number", async ({ page }) => {
  test.setTimeout(240_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const seen: string[] = [];
  const scan = async (label: string) => {
    const text = await page.evaluate(() => document.body.innerText);
    seen.push(...versionTokens(text).map((t) => `${label}: ${t}`));
  };
  const routes = [...SCREENS.map(([, route]) => route), ...EVAL_TABS.map((tab) => `evaluation?tab=${tab}`), ...MORE_ROUTES];
  for (const route of routes) {
    await ready(page, route, route);
    await openAll(page);
    await scan(route);
    const help = page.getByRole("button", { name: "What am I looking at?" });
    if (await help.count()) {
      await help.first().click();
      await scan(`${route} (help)`);
    }
  }
  await ready(page, "results", "results");
  for (const phase of ["Phase 1", "Phase 2", "Phase 3"]) {
    await page.getByRole("tab", { name: phase }).click();
    await openAll(page);
    await scan(`results: ${phase}`);
    // every table of the phase, one after the other
    const pick = page.getByLabel("Table", { exact: true });
    const count = await pick.locator("option").count();
    for (let i = 0; i < count; i++) {
      await pick.selectOption({ index: i });
      await expect(page.locator(".state.loading")).toHaveCount(0);
      await scan(`results: ${phase}, table ${i + 1}`);
    }
  }
  await page.goto(`/#/replay?${Q}&tour=1`);
  const tour = page.getByRole("dialog");
  await expect(tour).toContainText("Step 1 of");
  for (let step = 0; step < 12; step++) {
    await scan(`tour step ${step + 1}`);
    const next = tour.getByRole("button", { name: "Next" });
    if (!(await next.count())) break;
    await next.click();
  }
  expect(seen).toEqual([]);
});
