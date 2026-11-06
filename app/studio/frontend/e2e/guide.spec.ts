import { expect, test, type Page } from "@playwright/test";

// The user guide's screenshots (docs/images/studio/), light theme at 1280x720. They need the
// case studies and the watch demo under results/raw/, so they run on purpose only, against a
// server over this repository's results:
//   python e2e/serve.py 8799 --results ../../../results &
//   GUIDE_SHOTS=1 npx playwright test guide
// One test per screenshot, so `-g <name>` refreshes one of them.
const OUT = "../../../docs/images/studio";

test.skip(!process.env.GUIDE_SHOTS, "set GUIDE_SHOTS=1 to refresh the user guide's screenshots");
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
});

async function shot(page: Page, route: string, name: string, end = false, tab = "") {
  await page.goto(`/#/${route}`);
  await expect(page.locator("main h2").first()).toBeVisible();
  await expect(page.locator(".state.loading")).toHaveCount(0);
  if (name === "home") await expect(page.getByText("Try it on")).toBeVisible();
  if (end) {
    await page.getByRole("button", { name: "Jump to the end" }).click();
    await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
  }
  if (tab) await page.getByRole("tab", { name: tab }).click();
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

const SHOTS: [string, string, boolean?, string?][] = [
  ["home", "home"],
  ["runs", "runs"],
  ["launch", "launch"],
  ["replay?root=replay&path=20261102_demo_feature_agentic", "replay", true, "Agents"],
  ["replay?root=replay&path=20261101_manager_conflict_step_back", "step_back", true, "Agents"],
  ["compare?a=replay:20261101_toy_clean_offline&b=replay:20261102_demo_feature_agentic", "compare"],
  ["cases?name=shotgun-safe", "case_study"],
  ["watch?root=results&path=raw/watch_demo/watch", "watch"],
  ["results", "results"],
  ["evaluation?tab=audit", "evaluation"],
  ["reports?root=replay&path=20261030_demo_feature_advisory_v1/report.json", "saved_report"],
];

test("user guide screenshot: project", async ({ page }) => {
  await page.goto("/#/replay?root=replay&path=20261102_demo_feature_agentic");
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await page.getByRole("tree", { name: "Project tree" }).getByRole("treeitem", { name: /^_round_money\(\)/ }).click();
  await expect(page.getByLabel("Details").locator(".diff")).toContainText("def _round_money");
  await page.screenshot({ path: `${OUT}/project.png` });
});

test("user guide screenshots: before_after and before_after_diff", async ({ page }) => {
  await page.goto("/#/after?root=replay&path=20261102_demo_feature_agentic");
  await expect(page.getByLabel("Before and after")).toContainText("everything runs");
  await page.screenshot({ path: `${OUT}/before_after.png` });
  await page.getByRole("group", { name: "Before tree" }).getByRole("button", { name: /^reports\.py/ }).click();
  await page.getByRole("region", { name: "change 1 of 1" }).scrollIntoViewIfNeeded();
  await page.evaluate(() => document.querySelector(".file-diff")?.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: `${OUT}/before_after_diff.png` });
});

for (const [route, name, end, tab] of SHOTS) {
  test(`user guide screenshot: ${name}`, async ({ page }) => {
    await shot(page, route, name, end, tab);
  });
}
