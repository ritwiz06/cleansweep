import { expect, test, type Page } from "@playwright/test";

const V2 = "20261101_toy_clean_offline";
const V1 = "20261030_demo_feature_advisory_v1";
const REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)";

async function open(page: Page, route: string) {
  await page.goto(`/#/${route}`);
}

test("runs list offers the shipped recordings and opens a replay", async ({ page }) => {
  await open(page, "runs");
  const row = page.locator(`tr[data-run="${V2}"]`);
  await expect(row).toContainText("everything runs");
  await expect(page.locator(`tr[data-run="${V1}"]`)).toContainText("v1 sweep");
  await row.getByRole("link", { name: "Replay" }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${V2}` })).toBeVisible();
});

test("replay of a v2 run: transport, timeline, agents, boards, packages and report", async ({ page }) => {
  await open(page, `replay?root=replay&path=${V2}`);
  const transport = page.getByLabel("Replay controls");
  await expect(transport).toContainText("event 0 of 234");
  await page.getByRole("button", { name: "Next decision" }).click();
  await expect(page.getByLabel("Manager decisions")).toContainText("P1 kept");
  await page.getByRole("button", { name: "Step" }).click();
  await page.getByLabel("Speed").fill("50");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await expect(transport).toContainText("event 234 of 234");
  await expect(page.getByLabel("Run metrics")).toContainText("everything runs");
  await expect(page.getByLabel("Phase timeline")).toContainText("EXECUTE");
  await expect(page.locator('[data-agent="investigator"]')).toContainText("×");
  await expect(page.getByLabel("Agent graph")).toContainText("reporter");

  await page.getByRole("tab", { name: /Message board/ }).click();
  await page.getByLabel("Message type").selectOption("verdict");
  await expect(page.locator(".message").first()).toContainText("verdict");

  await page.getByRole("tab", { name: /Items/ }).click();
  await expect(page.getByLabel("Item board")).toContainText("Rolled back");
  await page.locator(".stage-kept .item-card").first().click();
  await expect(page.getByRole("dialog")).toContainText("Evidence chain");
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByRole("tab", { name: /Work packages/ }).click();
  await page.locator(".package-row", { hasText: "P1" }).first().click();
  await expect(page.locator(".package-detail")).toContainText("import os");
  await page.getByRole("button", { name: /Show blueprint.md/ }).click();
  await expect(page.locator(".package-main")).toContainText("P1");

  await page.getByRole("tab", { name: "Report" }).click();
  await expect(page.locator(".markdown").first()).toContainText("everything runs");
});

test("an artifact link opens the cached artifact", async ({ page }) => {
  await open(page, `replay?root=replay&path=${V2}`);
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await page.getByRole("tab", { name: /Message board/ }).click();
  await page.getByLabel("Message type").selectOption("package_applied");
  await page.locator(".message .artifact").first().click();
  await expect(page.getByRole("dialog")).toContainText("diff");
});

test("compare two runs side by side", async ({ page }) => {
  await open(page, "compare");
  await page.getByLabel("Run A").selectOption(`replay:${V2}`);
  await page.getByLabel("Run B").selectOption("results:raw/watch_a/clean-001");
  await expect(page.getByLabel("Comparison")).toContainText("lines removed");
  await expect(page.getByLabel("Comparison")).toContainText("44");
});

test("case study with the LLM-reviewer label", async ({ page }) => {
  await open(page, "cases");
  await page.getByRole("button", { name: /proj_a/ }).click();
  await expect(page.getByText("tests passing before")).toBeVisible();
  await page.getByRole("tab", { name: /Review sheet/ }).click();
  await expect(page.getByLabel("Review sheet")).toContainText(REVIEW_LABEL);
  await expect(page.getByLabel("Review sheet")).toContainText("a string may call it");
  await page.getByRole("tab", { name: "Diff" }).click();
  await expect(page.locator(".diff")).toContainText("def old");
});

test("watch folder: commits, slop over time, decisions", async ({ page }) => {
  await open(page, "watch");
  await page.getByLabel("Watch folder").selectOption("results:raw/watch_a");
  await expect(page.getByText("slop is 12.0% of the Python lines")).toBeVisible();
  await expect(page.getByText("Slop over time")).toBeVisible();
  await expect(page.getByLabel("Simulated watch")).toBeVisible();
});

test("results: v1 and v2 tables and figures", async ({ page }) => {
  await open(page, "results");
  await expect(page.getByLabel("main_table.csv")).toContainText("cleansweep-gatekeeper");
  await expect(page.locator(".gallery img").first()).toBeVisible();
  await page.getByRole("tab", { name: "v2" }).click();
  await expect(page.getByText(/Tables/)).toBeVisible();
});

test("dashboard parity: v1 live sweep replay", async ({ page }) => {
  await open(page, "sweeps");
  await page.locator(`tr[data-run="${V1}"]`).getByRole("link", { name: "Replay" }).click();
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await expect(page.getByText("Behavior changed: no")).toBeVisible();
  await expect(page.getByText("7/7")).toBeVisible();
  await expect(page.getByText("The probes caught a behavior change:")).toHaveCount(2);
  await expect(page.getByLabel("Reviewer plan")).toContainText("leftover_file");
});

test("dashboard parity: scheduler, baselines, data, guard", async ({ page }) => {
  await open(page, "scheduler");
  await expect(page.getByLabel("Policy means")).toContainText("every_pr");
  await page.getByLabel("Policy", { exact: true }).selectOption("daily");
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  await open(page, "baselines");
  await expect(page.getByLabel("Main table")).toContainText("tools_only");
  await expect(page.getByLabel("Paired tests")).toBeVisible();
  await open(page, "data");
  await expect(page.getByLabel("Association rules")).toBeVisible();
  await page.getByRole("tab", { name: "cluster" }).click();
  await expect(page.getByLabel("Detection by category")).toBeVisible();
  await open(page, "guard");
  await expect(page.getByLabel("Guard strength")).toContainText("mutants");
  await expect(page.getByLabel("False alarms")).toBeVisible();
});

test("launch an offline clean run and follow it live", async ({ page }) => {
  await open(page, "launch");
  await expect(page.getByLabel("Target")).toHaveValue("toy");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: /Live run/ })).toBeVisible();
  await expect(page.getByText("Run finished.")).toBeVisible({ timeout: 100_000 });
  await expect(page.getByLabel("Run metrics")).toContainText("everything runs");
  await open(page, "launch");
  await expect(page.locator(".jobs")).toContainText("done");
});

test("bad launch requests show the server's reason", async ({ page }) => {
  await open(page, "launch");
  await page.getByLabel("Target").selectOption("path");
  await page.getByLabel("Absolute path").fill("relative/folder");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("alert")).toContainText("absolute path");
});

test("every screen renders in both themes at 1280x720", async ({ page }) => {
  const routes = [
    "runs",
    "launch",
    `replay?root=replay&path=${V2}`,
    "compare",
    "cases?name=proj_a",
    "watch?root=results&path=raw/watch_a",
    "results",
    "sweeps",
    `replay?root=replay&path=${V1}`,
    "scheduler",
    "baselines",
    "data",
    "guard",
  ];
  for (const theme of ["light", "dark"]) {
    await open(page, "runs");
    const toggle = page.getByRole("button", { name: "Switch theme" });
    if ((await page.evaluate(() => document.documentElement.dataset.theme)) !== theme) await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const route of routes) {
      await open(page, route);
      await expect(page.locator("main h2").first()).toBeVisible();
      await expect(page.locator(".state.loading")).toHaveCount(0);
      await expect(page.locator(".state.error")).toHaveCount(0);
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width, `${route} fits 1280 px`).toBeLessThanOrEqual(1280);
      await page.screenshot({ path: `test-results/screens/${theme}-${route.split("?")[0]}-${routes.indexOf(route)}.png` });
    }
  }
});
