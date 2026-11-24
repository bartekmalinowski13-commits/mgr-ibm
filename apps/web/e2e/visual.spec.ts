import { expect, type Page, test } from "@playwright/test";
import { mockApi, PROJECT, RUN_A, RUN_A_DONE, RUN_B_DONE } from "./fixtures/mock-api";
import { expectAccessible } from "./helpers";

/**
 * ADR-0019 screens against a mocked API (no stack needed): WCAG check on each screen and a
 * screenshot next to the mock-up in docs/design/direction-v1 (written to test-results/visual).
 * Set VISUAL_DIR to write the screenshots elsewhere.
 */
const OUT = process.env.VISUAL_DIR ?? "test-results/visual";

async function shot(page: Page, name: string): Promise<void> {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}

test.describe("fabrication drawing screens (desktop)", () => {
  test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });

  test("BOM", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/runs/${RUN_B_DONE}/bom`);
    await page.locator("tbody tr").filter({ hasText: "U3" }).click();
    await expect(page.getByRole("complementary", { name: /U3/ })).toBeVisible();
    await expectAccessible(page);
    await shot(page, "bom");
  });

  test("A/B comparison", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/projects/${PROJECT}/compare?a=${RUN_A_DONE}&b=${RUN_B_DONE}`);
    await expect(page.getByText("C12").first()).toBeVisible();
    await expectAccessible(page);
    await shot(page, "compare");
  });

  test("live run", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/runs/${RUN_A}`);
    await expect(page.getByRole("list", { name: /hybryda/ })).toBeVisible();
    await expectAccessible(page);
    await shot(page, "run");
  });

  test("start", async ({ page }) => {
    await mockApi(page);
    await page.goto("/start");
    await expect(page.getByRole("heading", { name: /Cześć, Bartek/ })).toBeVisible();
    await expectAccessible(page);
    await shot(page, "start");
  });
});

test.describe("fabrication drawing screens (phone, 375 px)", () => {
  test.use({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, hasTouch: true });

  for (const [name, path] of [
    ["start", "/start"],
    ["run", `/runs/${RUN_A}`],
    ["bom", `/runs/${RUN_B_DONE}/bom`],
    ["compare", `/projects/${PROJECT}/compare?a=${RUN_A_DONE}&b=${RUN_B_DONE}`],
  ] as const) {
    test(`${name} has no horizontal page scroll and passes axe`, async ({ page }) => {
      await mockApi(page);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await expectAccessible(page);
      await shot(page, `${name}-375`);
    });
  }
});

test("component preview (/design) renders the ADR-0019 base components and passes axe", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/design");
  await expect(
    page.getByRole("heading", { name: "Komponenty rysunku wykonawczego" }),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Tabliczka rysunkowa" })).toBeVisible();
  await expectAccessible(page);
  await shot(page, "design");
});
