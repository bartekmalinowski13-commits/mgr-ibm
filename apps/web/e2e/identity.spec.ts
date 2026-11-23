import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

// Visual identity (ADR-0020): every screen passes axe and is captured at 375 and 1440 px.
// Screenshots go to test-results/screenshots (SCREENSHOT_DIR=docs/design/screenshots refreshes the committed set); the data is a fixture
// project created by the test, never customer data.
const FIXTURE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../evals/fixtures/kicad/pulse-ox",
);
const OUT =
  process.env.SCREENSHOT_DIR ??
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../test-results/screenshots");

const SIZES = [
  { name: "1440", width: 1440, height: 900 },
  { name: "375", width: 375, height: 812 },
] as const;

async function snap(page: Page, name: string, size: string, full = true) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.waitForTimeout(400);
  await expectAccessible(page);
  await page.screenshot({ path: path.join(OUT, `${name}-${size}.png`), fullPage: full });
}

test("Plex fonts render Polish diacritics", async ({ page }) => {
  await page.goto("/login");
  await page.setContent(
    "<p style=\"font-family:'IBM Plex Sans'\">Zażółć gęślą jaźń</p><h1 style=\"font-family:'IBM Plex Sans Condensed';font-weight:600\">Zażółć gęślą jaźń</h1>",
  );
  const ok = await page.evaluate(async () => {
    await document.fonts.load("16px 'IBM Plex Sans'", "Zażółć gęślą jaźń");
    await document.fonts.load("600 16px 'IBM Plex Sans Condensed'", "Zażółć gęślą jaźń");
    return (
      document.fonts.check("16px 'IBM Plex Sans'", "ąćęłńóśźż") &&
      document.fonts.check("600 16px 'IBM Plex Sans Condensed'", "ąćęłńóśźż")
    );
  });
  expect(ok).toBe(true);
});

test("every screen: axe + screenshot at 375 and 1440", async ({ page }) => {
  test.setTimeout(480_000);
  const id = unique();
  for (const size of SIZES) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto("/login");
    await snap(page, "01-brand-login", size.name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, `ident-${id}@medtech.example`, "Anna");
  await snap(page, "02-onboarding", "1440");
  await createOrganisation(page, `Identity ${id}`);

  await page.getByRole("link", { name: "Projekty" }).first().click();
  await snap(page, "03-projects-empty", "1440");
  await page.getByLabel("Nazwa projektu").fill("Pulsoksymetr");
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await page.waitForURL("**/projects/*");
  const files = fs.readdirSync(FIXTURE).filter((f) => f.includes(".kicad_"));
  await page.getByTestId("file-input").setInputFiles(files.map((f) => path.join(FIXTURE, f)));
  await expect(page.getByText("Gotowy")).toHaveCount(files.length, { timeout: 120_000 });
  const projectUrl = page.url();

  await page.getByRole("button", { name: "Uruchom przebieg" }).click();
  const dialog = page.getByRole("dialog", { name: "Nowy przebieg" });
  await dialog.getByText("Oba i porównanie").click();
  await snap(page, "04-new-run", "1440", false);
  await dialog.getByRole("button", { name: "Uruchom przebieg" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);
  await page.getByRole("link", { name: "Porównaj warianty A i B" }).click({ timeout: 120_000 });
  await expect(page.getByRole("table", { name: "Metryki przebiegów" })).toBeVisible();
  const compareUrl = page.url();

  for (const size of SIZES) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto("/start");
    await snap(page, "05-start", size.name);
    await page.goto("/projects");
    await snap(page, "06-projects", size.name);
    await page.goto(projectUrl);
    await snap(page, "07-project", size.name);
    await page.goto("/runs");
    await snap(page, "08-runs", size.name);
    await page.locator("tbody tr a").first().click();
    await expect(page.getByRole("heading", { name: "Zestawienie BOM" })).toBeVisible({
      timeout: 60_000,
    });
    await snap(page, "09-bom", size.name);
    await page.locator("tr[data-line]").first().click();
    await expect(page.locator("aside[aria-labelledby=panel-title]")).toBeVisible();
    await snap(page, "10-bom-panel", size.name, false);
    await page.goto(compareUrl);
    await expect(page.getByRole("table", { name: "Metryki przebiegów" })).toBeVisible();
    await snap(page, "11-compare", size.name);
    await page.goto("/kb");
    await snap(page, "12-knowledge-base", size.name);
    await page.goto("/audit");
    await snap(page, "13-audit", size.name);
    await page.goto("/settings");
    await snap(page, "14-settings", size.name);
  }
});
