import { expect, test, type Page } from "@playwright/test";

// The user guide's screenshots (docs/images/studio/), light theme at 1280x720. They need the
// case studies and the watch demo under results/raw/, so they run on purpose only, against a
// server over this repository's results:
//   python e2e/serve.py 8799 --results ../../../results &
//   GUIDE_SHOTS=1 npx playwright test guide
const OUT = "../../../docs/images/studio";

test.skip(!process.env.GUIDE_SHOTS, "set GUIDE_SHOTS=1 to refresh the user guide's screenshots");

async function shot(page: Page, route: string, name: string, end = false) {
  await page.goto(`/#/${route}`);
  await expect(page.locator("main h2").first()).toBeVisible();
  await expect(page.locator(".state.loading")).toHaveCount(0);
  if (end) {
    await page.getByRole("button", { name: "Jump to the end" }).click();
    await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
  }
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

test("user guide screenshots", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await shot(page, "runs", "runs");
  await shot(page, "launch", "launch");
  await shot(page, "replay?root=replay&path=20261102_demo_feature_agentic", "replay", true);
  await shot(page, "replay?root=replay&path=20261101_manager_conflict_step_back", "step_back", true);
  await shot(page, "compare?a=replay:20261101_toy_clean_offline&b=replay:20261102_demo_feature_agentic", "compare");
  await shot(page, "cases?name=shotgun-safe", "case_study");
  await shot(page, "watch?root=results&path=raw/watch_demo/watch", "watch");
  await shot(page, "results", "results");
  await shot(page, "evaluation?tab=audit", "evaluation");
  await shot(page, "reports?root=replay&path=20261030_demo_feature_advisory_v1/report.json", "saved_report");
});
