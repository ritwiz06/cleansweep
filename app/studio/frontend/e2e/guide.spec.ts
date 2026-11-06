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

async function shot(page: Page, route: string, name: string, end = false) {
  await page.goto(`/#/${route}`);
  await expect(page.locator("main h2").first()).toBeVisible();
  await expect(page.locator(".state.loading")).toHaveCount(0);
  if (name === "home") await expect(page.getByText("Try it on")).toBeVisible();
  if (end) {
    await page.getByRole("button", { name: "Jump to the end" }).click();
    await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
  }
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

const SHOTS: [string, string, boolean?][] = [
  ["home", "home"],
  ["runs", "runs"],
  ["launch", "launch"],
  ["replay?root=replay&path=20261102_demo_feature_agentic", "replay", true],
  ["replay?root=replay&path=20261101_manager_conflict_step_back", "step_back", true],
  ["compare?a=replay:20261101_toy_clean_offline&b=replay:20261102_demo_feature_agentic", "compare"],
  ["cases?name=shotgun-safe", "case_study"],
  ["watch?root=results&path=raw/watch_demo/watch", "watch"],
  ["results", "results"],
  ["evaluation?tab=audit", "evaluation"],
  ["reports?root=replay&path=20261030_demo_feature_advisory_v1/report.json", "saved_report"],
];

for (const [route, name, end] of SHOTS) {
  test(`user guide screenshot: ${name}`, async ({ page }) => {
    await shot(page, route, name, end);
  });
}
