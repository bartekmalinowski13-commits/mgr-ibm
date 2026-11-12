import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

const FIXTURE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../evals/fixtures/kicad/pulse-ox",
);

test("compare variants A and B on the same project", async ({ page }) => {
  const id = unique();
  await signIn(page, `cmp-${id}@medtech.example`, "Piotr");
  await createOrganisation(page, `Gamma ${id}`);
  await page.getByRole("link", { name: "Projekty" }).first().click();
  await page.getByLabel("Nazwa projektu").fill("Pulsoksymetr");
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await page.waitForURL("**/projects/*");
  const fs = await import("node:fs");
  const files = fs.readdirSync(FIXTURE).filter((f) => f.includes(".kicad_"));
  await page.getByTestId("file-input").setInputFiles(files.map((f) => path.join(FIXTURE, f)));
  await expect(page.getByText("Gotowy")).toHaveCount(files.length, { timeout: 120_000 });

  await page.getByRole("button", { name: "Uruchom przebieg" }).click();
  const dialog = page.getByRole("dialog", { name: "Nowy przebieg" });
  await dialog.getByText("Oba i porównanie").click();
  await dialog.getByRole("button", { name: "Uruchom przebieg" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);

  await page.getByRole("link", { name: "Porównaj warianty A i B" }).click({ timeout: 90_000 });
  await expect(page.getByRole("table", { name: "Metryki przebiegów" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /między wariantami|tak samo/ })).toBeVisible();
  await expectAccessible(page);
});
