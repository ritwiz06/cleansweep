import { expect, type Page } from "@playwright/test";

// Moving through a replay in the tests: a run's slider takes the keys (Page Down moves ten
// events); a Phase 1 replay has its own End button.

export async function scrubTo(page: Page, n: number) {
  const slider = page.locator(".run-scrub");
  await slider.focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < Math.floor(n / 10); i++) await page.keyboard.press("PageDown");
  for (let i = 0; i < n % 10; i++) await page.keyboard.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuenow", String(n));
  await slider.blur();
}

export async function toEnd(page: Page) {
  await expect(page.locator("main h2").first()).toBeVisible();
  await expect(page.locator(".state.loading")).toHaveCount(0);
  const slider = page.locator(".run-scrub");
  if (await slider.count()) {
    await slider.focus();
    await page.keyboard.press("End");
    await expect(slider).toHaveAttribute("aria-valuenow", (await slider.getAttribute("aria-valuemax")) || "");
    await slider.blur();
    return;
  }
  const end = page.getByRole("button", { name: "Jump to the end" });
  if (await end.count()) {
    await end.click();
    await expect(page.getByLabel("Replay controls")).toContainText(/event (\d+) of \1(?!\d)/);
  }
}
