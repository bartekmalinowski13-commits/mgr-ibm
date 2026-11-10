import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("new project → upload KiCad → run A + B → compare → BOM with provenance", async ({ page }) => {
  await page.goto("/projects");
  await page.getByLabel("Nazwa projektu, np. Monitor EKG").fill("Wzmacniacz EEG, 2 kanały");
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Wzmacniacz EEG, 2 kanały" }),
  ).toBeVisible();

  await page.getByTestId("design-files").setInputFiles({
    name: "eeg-2ch.kicad_sch",
    mimeType: "text/plain",
    buffer: Buffer.from("(kicad_sch (version 20231120))"),
  });
  await expect(page.getByText("Gotowy")).toBeVisible();

  await page.getByRole("button", { name: "Uruchom przebieg" }).click();
  const dialog = page.getByRole("dialog", { name: "Nowy przebieg" });
  await dialog.getByLabel("Nazwa*").fill("EEG – przegląd");
  await expect(dialog.getByRole("radio", { name: /A \+ B/ })).toBeChecked();
  const axe = await new AxeBuilder({ page }).include("[role=dialog]").analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
  await dialog.getByRole("button", { name: "Uruchom przebieg" }).click();

  await expect(page).toHaveURL(/\/compare\?a=.+&b=.+/);
  await expect(page.getByText(/Dane z symulatora modelu/)).toBeVisible();
  await expect(page.getByRole("row", { name: /Wywołania LLM/ })).toBeVisible({ timeout: 15_000 });

  await page.getByRole("link", { name: /B · hybryda/ }).click();
  const table = page.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(23);
  await page.getByLabel("Tylko pozycje z uwagami").check();
  await expect(table.getByRole("row")).toHaveCount(4);
  await table.getByRole("button", { name: "J1" }).click();
  await expect(page.getByRole("dialog", { name: /Szczegóły pozycji/ })).toContainText(
    "iec60601.patient_connector",
  );
});

test("Allegro .brd is refused with a way forward", async ({ page }) => {
  await page.goto("/projects");
  await page.getByLabel("Nazwa projektu, np. Monitor EKG").fill("Pompa infuzyjna");
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await page.getByTestId("design-files").setInputFiles({
    name: "pump.brd",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("binary"),
  });
  await expect(page.getByRole("alert")).toContainText("IPC-2581");
  await expect(page.getByRole("button", { name: "Uruchom przebieg" })).toBeDisabled();
});

test("CSV export downloads the BOM", async ({ page }) => {
  await page.goto("/runs");
  await page.getByRole("link", { name: /Otwórz przebieg A/ }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Eksportuj CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
});

test("interface switches to English", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: "English" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Organisation settings");
  await page.reload();
  await expect(page.getByRole("link", { name: "Runs" })).toBeVisible();
});
