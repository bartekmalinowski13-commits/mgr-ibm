import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

const SHEET = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../evals/fixtures/datasheets/adi-ad8232.md",
);

test("add a datasheet to the organisation's knowledge base and see it indexed", async ({
  page,
}) => {
  const id = unique();
  await signIn(page, `kb-${id}@medtech.example`, "Kasia");
  await createOrganisation(page, `Kappa ${id}`);
  await page.getByRole("link", { name: "Baza wiedzy" }).click();
  await expect(page.getByText(/Brak dokumentów organizacji/)).toBeVisible();
  await expectAccessible(page);

  await page.getByLabel("Plik (PDF, Markdown, tekst)").setInputFiles(SHEET);
  await page.getByLabel("Producent").fill("Analog Devices");
  await page.getByRole("button", { name: "Dodaj do bazy" }).click();
  await expect(page.getByText("adi-ad8232.md", { exact: true })).toBeVisible();
  await expect(page.getByText("Zaindeksowany")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/fragment/)).toBeVisible();

  await page.getByRole("tab", { name: "Korpus globalny" }).click();
  await expect(page.getByText(/tylko odczyt/)).toBeVisible();
  await expectAccessible(page);
});
