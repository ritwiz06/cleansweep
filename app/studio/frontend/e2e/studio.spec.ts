import { expect, test, type Page } from "@playwright/test";

const V2 = "20261101_toy_clean_offline";
const V1 = "20261030_demo_feature_advisory_v1";
const DEMO = "20261102_demo_feature_agentic";
const REVIEW_LABEL = "LLM-reviewer acceptance (independent model, blinded)";

async function open(page: Page, route: string) {
  await page.goto(`/#/${route}`);
}

test("home: clean a folder with readable errors, and the recent runs", async ({ page }) => {
  await open(page, "");
  await expect(page.getByRole("heading", { name: "Clean a folder" })).toBeVisible();
  const folder = page.getByLabel("Folder to clean");
  const start = page.getByRole("button", { name: "Start" });
  await start.click();
  await expect(page.getByRole("alert")).toContainText("Paste the path of a folder first.");
  await folder.fill("relative/folder");
  await start.click();
  await expect(page.getByRole("alert")).toContainText("absolute path");
  await folder.fill("/no/such/folder");
  await start.click();
  await expect(page.getByRole("alert")).toContainText("There is no folder at /no/such/folder.");
  await page.getByLabel("Mode").getByText("Thorough").click();
  await expect(page.getByRole("radio", { name: "Thorough" })).toBeChecked();
  await expect(page.getByText("Also LLM rewrites")).toBeVisible();
  await page.getByRole("button", { name: "Toy repo" }).click();
  await expect(folder).toHaveValue(/toy_repo$/);
  await expect(page.getByRole("alert")).toHaveCount(0);
  const recent = page.getByLabel("Recent runs");
  await recent.locator(`[data-run="${V2}"]`).getByRole("link", { name: "Open" }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${V2}` })).toBeVisible();
});

test("home: Try the demo opens the demo app's recording in Replay", async ({ page }) => {
  await open(page, "");
  await page.getByRole("link", { name: "Try the demo" }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${DEMO}` })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("the tour walks through the replay screen and Escape ends it", async ({ page }) => {
  await open(page, "");
  await page.getByRole("link", { name: "Take the tour" }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${DEMO}` })).toBeVisible();
  const tour = page.getByRole("dialog");
  await expect(tour).toContainText("Step 1 of 6");
  await expect(tour.getByRole("heading", { name: "Play the recording" })).toBeVisible();
  // the tour shows the run part-way, and the card takes the focus
  await expect(page.getByLabel("Replay controls")).not.toContainText("event 0 of");
  await expect(tour.getByRole("button", { name: "Next" })).toBeFocused();
  await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour).toContainText("Step 2 of 6");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(tour.getByRole("heading", { name: "The agent team" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Agents" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(tour).toContainText("Step 4 of 6");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).not.toHaveURL(/tour=1/);
});

test("each screen's help popover opens with one line and closes with Escape", async ({ page }) => {
  for (const route of ["home", "runs", `replay?root=replay&path=${DEMO}`, `after?root=replay&path=${DEMO}`, "compare", "cases", "watch", "results", "evaluation", "reports"]) {
    await open(page, route);
    const help = page.getByRole("button", { name: "What am I looking at?" });
    await help.click();
    await expect(help).toHaveAttribute("aria-expanded", "true");
    const note = page.getByRole("note");
    await expect(note, route).toBeVisible();
    expect((await note.innerText()).split("\n").length, route).toBe(1);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("note")).toHaveCount(0);
    await expect(help).toBeFocused();
  }
});

test("runs list offers the shipped recordings and opens a replay", async ({ page }) => {
  await open(page, "runs");
  const row = page.locator(`tr[data-run="${V2}"]`);
  await expect(row).toContainText("everything runs");
  await expect(page.locator(`tr[data-run="${V1}"]`)).toContainText("Phase 1 sweep");
  await row.getByRole("link", { name: "Replay" }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${V2}` })).toBeVisible();
});

test("replay of a v2 run: transport, timeline, agents, boards, packages and report", async ({ page }) => {
  await open(page, `replay?root=replay&path=${V2}`);
  const transport = page.getByLabel("Replay controls");
  await expect(transport).toContainText("event 0 of 234");
  await page.getByRole("tab", { name: "Agents" }).click();
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

test("project view: the tree follows the events, and a node shows its evidence, diff and checks", async ({ page }) => {
  await open(page, `replay?root=replay&path=${DEMO}`);
  const tree = page.getByRole("tree", { name: "Project tree" });
  await expect(page.getByText("This run saved no file list")).toBeVisible();
  // mid-investigation: an Investigator is on _print_low_stock
  await page.getByLabel("Scrubber").fill("69");
  const unit = tree.locator('[data-key="unit:bookshelf/inventory.py::_print_low_stock"]');
  await expect(unit).toHaveClass(/st-investigating/);
  await expect(unit.locator('svg[data-role="investigator"]')).toHaveCount(1);
  await expect(unit.getByRole("treeitem")).toHaveAccessibleName(/investigating, last Investigator #3/);
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await expect(tree.locator('[data-key="file:bookshelf/inventory_old.py"]')).toHaveClass(/st-kept/);
  await expect(unit).toHaveClass(/st-kept/);
  await tree.getByRole("treeitem", { name: /^_round_money\(\)/ }).click();
  const details = page.getByLabel("Details");
  await expect(details).toContainText("rolled back");
  await expect(details).toContainText("Evidence chain");
  await expect(details.locator(".diff")).toContainText("def _round_money");
  await expect(details).toContainText("differ");
  await page.getByRole("tab", { name: /Items/ }).click();
  await expect(page.getByLabel("Item board")).toContainText("Suggest");
});

test("before / after: both trees, the numbers, and each change with the decisions behind it", async ({ page }) => {
  await open(page, "runs");
  await page.locator(`tr[data-run="${DEMO}"]`).getByRole("link", { name: "Before / after" }).click();
  await expect(page.getByRole("heading", { name: `Before / after: ${DEMO}` })).toBeVisible();
  const before = page.getByRole("group", { name: "Before tree" });
  const after = page.getByRole("group", { name: "After tree" });
  await expect(before.locator("del", { hasText: "inventory_old.py" })).toBeVisible();
  await expect(before).toContainText("removed");
  await expect(after).not.toContainText("inventory_old.py");
  await expect(after.getByRole("button", { name: /^reports\.py/ })).toContainText("+2");
  const numbers = page.getByLabel("Before and after");
  await expect(numbers).toContainText(/229\s*→\s*182/);
  await expect(numbers).toContainText(/12\s*→\s*12/);
  await expect(numbers).toContainText("1 removed: isbn_checksum_ok");
  await expect(page.getByLabel("Slop by category")).toContainText("leftover file");
  await expect(page.getByText("Behavior that nothing tests isn't covered")).toBeVisible();
  await before.getByRole("button", { name: /^reports\.py/ }).click();
  const change = page.getByRole("region", { name: "change 1 of 1" });
  await expect(change).toContainText("duplicate");
  await expect(change).toContainText("Investigator #6");
  await expect(change).toContainText("P5 kept");
  await expect(change).toContainText("public names unchanged");
  await expect(change.getByRole("table")).toContainText("normalize_isbn");
  await page.getByRole("link", { name: "Replay", exact: true }).click();
  await expect(page.getByRole("heading", { name: `Replay: ${DEMO}` })).toBeVisible();
});

test("presentation mode: large captions, a fixed pace, and the space bar jumps to the next decision", async ({ page }) => {
  await open(page, `replay?root=replay&path=${DEMO}`);
  await page.getByRole("link", { name: "Present" }).click();
  await expect(page.locator("nav.sidebar")).toHaveCount(0);
  const caption = page.getByLabel("Caption");
  const controls = page.getByLabel("Presentation controls");
  await expect(caption).toContainText("Manager starts cleaning shop_app in safe mode");
  expect(await caption.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(32);
  await page.keyboard.press("Space");
  await expect(caption).toContainText("Manager decides to continue");
  await expect(controls).toContainText("step 9 of 158");
  await page.keyboard.press("ArrowRight");
  await expect(caption).toContainText("Manager moves on to the baseline");
  await expect(page.getByLabel("Active agent")).toContainText("runs the phases");
  // one step every 1.5 s, whatever the step took in the run
  await page.keyboard.press("p");
  await expect(controls).toContainText("step 11 of 158", { timeout: 2500 });
  await page.keyboard.press("p");
  await page.keyboard.press("Space");
  await page.keyboard.press("Space");
  await expect(controls).toContainText("step 22 of 158");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect(caption).toContainText("Investigator #1 checks who uses bookshelf/inventory_old.py");
  await expect(page.getByRole("tree", { name: "Project tree" }).locator(".tree-row.focus").first()).toBeVisible();
  // G switches to the agent graph and back; the agent at work is marked
  await page.keyboard.press("g");
  await expect(page).toHaveURL(/view=agents/);
  await expect(page.getByLabel("Agent graph")).toContainText("at work");
  await expect(page.getByRole("button", { name: "Agents" })).toHaveAttribute("aria-pressed", "true");
  await expect(controls).toContainText("step 25 of 158");
  await page.keyboard.press("g");
  await expect(page.getByRole("tree", { name: "Project tree" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: `Replay: ${DEMO}` })).toBeVisible();
});

test("presentation mode on before / after: the summary, then one change per slide", async ({ page }) => {
  await open(page, `after?root=replay&path=${DEMO}`);
  await page.getByRole("link", { name: "Present" }).click();
  const controls = page.getByLabel("Presentation controls");
  await expect(controls).toContainText("5 changes");
  await expect(page.getByLabel("Caption")).toContainText("everything runs");
  await expect(page.getByText("Behavior that nothing tests isn't covered").first()).toBeVisible();
  await page.keyboard.press("Space");
  await expect(controls).toContainText("change 1 of 5");
  await expect(page.getByLabel("Decisions")).toContainText("Manager");
  await page.keyboard.press("Space");
  await page.keyboard.press("Space");
  await expect(page.getByLabel("Caption")).toContainText("_clean_isbn()");
  await expect(page.getByLabel("Checks")).toContainText("public names unchanged");
  await page.keyboard.press("Shift+Space");
  await expect(controls).toContainText("change 2 of 5");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: `Before / after: ${DEMO}` })).toBeVisible();
});

test("export: one self-contained HTML report that opens from file:// with no server", async ({ page, context }, info) => {
  await open(page, `after?root=replay&path=${DEMO}`);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export HTML report" }).click();
  const file = info.outputPath(`cleansweep-${DEMO}.html`);
  await (await download).saveAs(file);
  expect((await download).suggestedFilename()).toBe(`cleansweep-${DEMO}.html`);
  const report = await context.newPage();
  const fetched: string[] = [];
  report.on("request", (r) => fetched.push(r.url()));
  await report.goto(`file://${file}`);
  await expect(report.getByRole("heading", { name: "CleanSweep cleanup: shop_app" })).toBeVisible();
  await expect(report.getByLabel("Before and after")).toContainText(/229\s*→\s*182/);
  await expect(report.getByRole("group", { name: "Before tree" }).locator("del", { hasText: "inventory_old.py" })).toBeVisible();
  await expect(report.getByRole("region", { name: "change 1 of 1" }).first()).toContainText("Investigator #3");
  await expect(report.locator("table.sbs").first()).toBeVisible();
  await expect(report.getByText("Left for a person (10)")).toBeVisible();
  // the page is styled (the tokens are inline) and fetched nothing but itself
  expect(await report.locator(".state-chip").first().evaluate((el) => getComputedStyle(el).borderRadius)).not.toBe("0px");
  expect(fetched.filter((u) => !u.startsWith("file://"))).toEqual([]);
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
  await expect(page.getByLabel("Comparison")).toContainText("Lines removed");
  await expect(page.getByLabel("Comparison")).toContainText("44");
});

test("case study with the LLM-reviewer label", async ({ page }) => {
  await open(page, "cases");
  await page.getByRole("button", { name: /^proj_a/ }).click();
  await expect(page.getByText("Tests passing, before → after")).toBeVisible();
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

test("results: Phase 1 and Phase 2 tables and figures", async ({ page }) => {
  await open(page, "results");
  await expect(page.getByLabel("main_table.csv")).toContainText("cleansweep-gatekeeper");
  await expect(page.locator(".gallery img").first()).toBeVisible();
  await page.getByRole("tab", { name: "Phase 2" }).click();
  await expect(page.getByText(/Tables/)).toBeVisible();
});

test("dashboard parity: Phase 1 live sweep replay", async ({ page }) => {
  await open(page, "sweeps");
  await page.locator(`tr[data-run="${V1}"]`).getByRole("link", { name: "Replay" }).click();
  await page.getByRole("button", { name: "Jump to the end" }).click();
  await expect(page.getByText("Behavior changed: no")).toBeVisible();
  await expect(page.getByText("7/7")).toBeVisible();
  await expect(page.getByText("The probes caught a behavior change:")).toHaveCount(2);
  await expect(page.getByLabel("Reviewer plan")).toContainText("leftover_file");
});

test("dashboard parity: a saved sweep report", async ({ page }) => {
  await open(page, "reports");
  await page.getByLabel("Sweep report").selectOption(`replay:${V1}/report.json`);
  await expect(page.getByText("Lines removed")).toBeVisible();
  await expect(page.locator(".stats-row")).toContainText("47");
  await expect(page.getByLabel("Cleanup plan")).toContainText("leftover_file");
  await page.locator("details summary").filter({ hasText: "leftover_file" }).first().click();
  await expect(page.getByText(/^cp '\.cleansweep\/quarantine\//).first()).toBeVisible();
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

test("evaluation: every tab loads, with the tiers and the LLM-judged labels", async ({ page }) => {
  await open(page, "evaluation");
  await expect(page.getByRole("heading", { name: "Evaluation" })).toBeVisible();
  const tabs: [string, string[]][] = [
    ["Phase 2", ["Injection benchmark", "Ablations", "Diff audit", "Probe strength", "Manager scenarios", "LLM reviewer", "Watch"]],
    ["Phase 3", ["Hypotheses", "Injection", "Real projects", "Audit", "Autonomy and cost"]],
  ];
  for (const [phase, names] of tabs) {
    await page.getByRole("group", { name: "Phase" }).getByRole("button", { name: phase }).click();
    for (const tab of names) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expect(page.locator(".state.loading")).toHaveCount(0);
      await expect(page.locator(".state.error")).toHaveCount(0);
    }
  }
  await page.getByRole("group", { name: "Phase" }).getByRole("button", { name: "Phase 2" }).click();
  await page.getByRole("tab", { name: "Probe strength" }).click();
  await expect(page.getByLabel("probe_strength.csv")).toContainText("swebench_t1");
  await expect(page.getByRole("img", { name: "Share of mutations and PatchDiff changes caught" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Share of mutations and PatchDiff changes caught" })).toContainText("(higher is better)");
  await page.getByRole("tab", { name: "LLM reviewer" }).click();
  await expect(page.locator("main")).toContainText("LLM-judged");
  await page.getByRole("tab", { name: "Diff audit" }).click();
  await expect(page.locator("main")).toContainText("reading tier: LLM-judged");
  await expect(page).toHaveURL(/tab=audit/);
  // the chart and the table name the methods alike
  await page.getByRole("tab", { name: "Injection benchmark" }).click();
  await expect(page.getByLabel("injection_seeds.csv")).toContainText("team");
  await expect(page.getByLabel("injection_seeds.csv")).not.toContainText("agentic");
  // presentation mode: one line instead of the tabs, the arrow keys move
  await page.getByRole("link", { name: "Present" }).click();
  await expect(page.locator(".present-nav")).toContainText("Injection benchmark · 1 of 12");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".present-nav")).toContainText("Ablations · 2 of 12");
  await page.keyboard.press("Escape");
  await expect(page.locator("nav.sidebar")).toBeVisible();
  // the judge panel replaces the human ratings; its table may not be built yet
  await page.getByRole("group", { name: "Phase" }).getByRole("button", { name: "Phase 3" }).click();
  await page.getByRole("tab", { name: "Audit", exact: true }).click();
  const panel = page.locator("section.card", { has: page.getByRole("heading", { name: "LLM judge panel" }) });
  await expect(panel).toContainText("no human checked these labels");
  await expect(page.locator("main")).not.toContainText(/human ratings|raters|human-validated/i);
});

// One screen as the user guide's review needs it: loaded, no error, nothing wider than 1280 px.
async function checkScreen(page: Page, label: string, shot: string) {
  await expect(page.locator("main h2").first(), label).toBeVisible();
  await expect(page.locator(".state.loading"), label).toHaveCount(0);
  await expect(page.locator(".state.error"), label).toHaveCount(0);
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width, `${label} fits 1280 px`).toBeLessThanOrEqual(1280);
  await page.screenshot({ path: `test-results/recordings/${shot}.png` });
}

test("every shipped recording through every screen, in both themes at 1280x720", async ({ page }) => {
  test.setTimeout(300_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const runs: { root: string; path: string; name: string; kind: string }[] = await (await page.request.get("/api/runs")).json();
  const shipped = runs.filter((r) => r.root === "replay");
  expect(shipped.filter((r) => r.kind === "v2").length).toBeGreaterThanOrEqual(4);
  for (const theme of ["light", "dark"]) {
    await open(page, "runs");
    if ((await page.evaluate(() => document.documentElement.dataset.theme)) !== theme) await page.getByRole("button", { name: /^(Dark|Light) theme$/ }).click();
    for (const run of shipped) {
      const q = `root=replay&path=${run.path}`;
      await open(page, `replay?${q}`);
      await page.getByRole("button", { name: "Jump to the end" }).click();
      await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
      if (run.kind === "v1") {
        await checkScreen(page, `${run.name} replay`, `${theme}-${run.name}-replay`);
        await open(page, `reports?root=replay&path=${run.path}/report.json`);
        await checkScreen(page, `${run.name} saved report`, `${theme}-${run.name}-report`);
        continue;
      }
      for (const tab of ["Project", "Agents", "Message board", "Items", "Work packages", "Report"]) {
        await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
        await checkScreen(page, `${run.name} ${tab}`, `${theme}-${run.name}-${tab.replace(" ", "_")}`);
      }
      for (const [route, view] of [[`after?${q}`, "after"], [`present?${q}`, "present"], [`after?${q}&present=1`, "present_after"]]) {
        await open(page, route);
        await checkScreen(page, `${run.name} ${view}`, `${theme}-${run.name}-${view}`);
      }
    }
  }
});

test("every screen renders in both themes at 1280x720", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // finished charts in the screenshots
  const routes = [
    "home",
    "runs",
    "launch",
    `replay?root=replay&path=${V2}`,
    "compare",
    "cases?name=proj_a",
    "watch?root=results&path=raw/watch_a",
    "results",
    "evaluation",
    "evaluation?tab=audit",
    "evaluation?tab=ablations",
    "evaluation?tab=v3-audit",
    "sweeps",
    `replay?root=replay&path=${V1}`,
    `reports?root=replay&path=${V1}/report.json`,
    "scheduler",
    "baselines",
    "data",
    "guard",
    "replay?root=replay&path=20261101_manager_conflict_step_back",
    "replay?root=replay&path=20261102_demo_feature_agentic",
    `after?root=replay&path=${DEMO}`,
    `after?root=replay&path=${V2}`,
    `present?root=replay&path=${DEMO}`,
    `after?root=replay&path=${DEMO}&present=1`,
  ];
  for (const theme of ["light", "dark"]) {
    await open(page, "runs");
    const toggle = page.getByRole("button", { name: /^(Dark|Light) theme$/ });
    if ((await page.evaluate(() => document.documentElement.dataset.theme)) !== theme) await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    for (const route of routes) {
      await open(page, route);
      await expect(page.locator("main h2").first()).toBeVisible();
      await expect(page.locator(".state.loading")).toHaveCount(0);
      await expect(page.locator(".state.error")).toHaveCount(0);
      const end = page.getByRole("button", { name: "Jump to the end" });
      if (await end.count()) {
        await end.click(); // a replay is shown at its last event
        await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
      }
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width, `${route} fits 1280 px`).toBeLessThanOrEqual(1280);
      await page.screenshot({ path: `test-results/screens/${theme}-${route.split("?")[0]}-${routes.indexOf(route)}.png` });
    }
  }
});
