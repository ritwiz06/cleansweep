import { expect, test, type Page } from "@playwright/test";

// Design review screenshots: every screen in both themes at 1280x720 and 1920x1080, named
// <screen>-<theme>-<width>.png. They show the real data: the shipped recordings, and a results
// folder that holds the case studies and the watch demo under raw/ (this repository's results/
// after the experiments ran), served on purpose:
//   python e2e/serve.py 8812 --results <results folder> &
//   STUDIO_E2E_PORT=8812 REVIEW_SHOTS=/path/to/folder npx playwright test review
// Add `-g <screen>` to refresh one screen.
const OUT = process.env.REVIEW_SHOTS || "";
const DEMO = "20261102_demo_feature_agentic";
const DEMO_Q = `root=replay&path=${DEMO}`;

test.skip(!OUT, "set REVIEW_SHOTS=<folder> to take the design review screenshots");

type Prepare = (page: Page) => Promise<void>;

// moves a replay to event n with the timeline's keys, then lets go of the focus
const scrub = (count: number): Prepare => async (page) => {
  const slider = page.getByRole("slider", { name: "Scrubber" });
  await slider.focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < Math.floor(count / 10); i++) await page.keyboard.press("PageDown");
  for (let i = 0; i < count % 10; i++) await page.keyboard.press("ArrowRight");
  await slider.blur();
};

const SCREENS: [string, string, Prepare?][] = [
  ["home", "home"],
  ["live-run", `run?${DEMO_Q}`, async (page) => {
    await expect(page.getByRole("heading", { name: /^Run: / })).toBeVisible();
  }],
  ["project-view", `replay?${DEMO_Q}`, scrub(260)],
  ["replay", `replay?${DEMO_Q}`, async (page) => {
    await scrub(69)(page);
    await page.getByRole("tab", { name: "Agents" }).click();
    await page.getByRole("heading", { name: "Agent team", exact: true }).scrollIntoViewIfNeeded();
  }],
  ["before-after", `after?${DEMO_Q}`],
  ["before-after-diff", `after?${DEMO_Q}`, async (page) => {
    await page.getByRole("group", { name: "Before tree" }).getByRole("button", { name: /^reports\.py/ }).click();
  }],
  ["compare", `compare?a=replay:20261101_toy_clean_offline&b=replay:${DEMO}`],
  ["case-studies", "cases?name=skill-seekers-safe"],
  ["watch", "watch?root=results&path=raw/watch_demo/watch"],
  ["results", "results"],
  ["evaluation", "evaluation"],
  ["saved-reports", "reports?root=replay&path=20261030_demo_feature_advisory_v1/report.json"],
  ["present-replay", `present?${DEMO_Q}`, async (page) => {
    for (let i = 0; i < 3; i++) await page.keyboard.press("Space");
  }],
  ["present-agents", `present?${DEMO_Q}&view=agents`, async (page) => {
    for (let i = 0; i < 3; i++) await page.keyboard.press("Space");
  }],
  ["present-after", `after?${DEMO_Q}&present=1`, async (page) => {
    for (let i = 0; i < 3; i++) await page.keyboard.press("Space");
  }],
  ["present-evaluation", "evaluation?present=1"],
  ["tour", `replay?${DEMO_Q}&tour=1`, async (page) => {
    await expect(page.getByRole("dialog")).toContainText("Step 1 of");
    for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  }],
];

const SIZES = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
];

async function setTheme(page: Page, theme: string) {
  await page.addInitScript((t) => localStorage.setItem("studio-theme", t), theme);
}

for (const [screen, route, prepare] of SCREENS) {
  test(`review screenshots: ${screen}`, async ({ browser }) => {
    for (const theme of ["light", "dark"]) {
      for (const size of SIZES) {
        const context = await browser.newContext({ viewport: size, reducedMotion: "reduce" });
        const page = await context.newPage();
        await setTheme(page, theme);
        await page.goto(`/#/${route}`);
        await expect(page.locator("main h2").first()).toBeVisible();
        await expect(page.locator(".state.loading")).toHaveCount(0);
        await expect(page.locator(".state.error")).toHaveCount(0);
        if (prepare) await prepare(page);
        await page.waitForTimeout(300);
        await page.screenshot({ path: `${OUT}/${screen}-${theme}-${size.width}.png` });
        await context.close();
      }
    }
  });
}
