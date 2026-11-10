import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/* Smoke: every screen renders and has no serious accessibility violations (WCAG 2.1 AA). */
const SCREENS = [
  "/",
  "/projects",
  "/runs",
  "/compare",
  "/knowledge",
  "/audit",
  "/settings",
  "/notifications",
];

for (const path of SCREENS) {
  test(`screen ${path} renders without a11y violations`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(
      serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    ).toEqual([]);
  });
}
