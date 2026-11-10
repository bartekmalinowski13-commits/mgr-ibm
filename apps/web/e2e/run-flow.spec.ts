import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

const FIXTURE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../evals/fixtures/kicad/ecg-frontend",
);
const FILES = [
  "ecg-frontend.kicad_pro",
  "ecg-frontend.kicad_sch",
  "afe.kicad_sch",
  "power.kicad_sch",
];

test("new run from a template -> live progress -> BOM -> provenance -> correction -> export", async ({
  page,
}) => {
  const id = unique();
  await signIn(page, `anna-${id}@medtech.example`, "Anna");
  await expectAccessible(page);
  await createOrganisation(page, `MedTech ${id}`);
  await expect(page.getByRole("heading", { name: "Cześć, Anna" })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("link", { name: "Projekty" }).first().click();
  await page.getByLabel("Nazwa projektu").fill("EKG front-end");
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await page.waitForURL("**/projects/*");
  await page.getByTestId("file-input").setInputFiles(FILES.map((f) => path.join(FIXTURE, f)));
  await expect(page.getByText("Gotowy")).toHaveCount(FILES.length, { timeout: 120_000 });
  await expectAccessible(page);

  await page.getByRole("link", { name: "Start" }).click();
  await page.getByRole("button", { name: /EKG noszony/ }).click();
  const dialog = page.getByRole("dialog", { name: "Nowy przebieg" });
  await expect(dialog.getByLabel("Część aplikacyjna")).toHaveValue("BF");
  await dialog.getByLabel("Projekt").selectOption({ label: "EKG front-end" });
  await dialog.getByText("B – hybryda").click();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Uruchom przebieg" }).click();

  await page.waitForURL("**/runs/*");
  await expect(page.getByRole("heading", { name: "Zestawienie BOM" })).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText("Gotowy")).toBeVisible();
  await expectAccessible(page);

  await page.getByTestId("reference-input").setInputFiles(path.join(FIXTURE, "reference_bom.csv"));
  await expect(page.getByText("F1 pozycji")).toBeVisible();
  await expect(page.getByText(/rozbieżnoś/)).toBeVisible();
  await expectAccessible(page);

  const row = page.locator("tbody tr").filter({ hasText: "C4" });
  await row.click();
  const panel = page.getByRole("complementary", { name: /Pozycja/ });
  await expect(panel.getByText("Pochodzenie pól")).toBeVisible();
  await panel.getByLabel("Producent").fill("Murata Manufacturing");
  await panel.getByLabel("Powód zmiany").fill("Zamiennik z magazynu");
  await panel.getByRole("button", { name: "Zapisz poprawkę" }).click();
  await expect(page.getByText("Zapisano poprawkę jako wersję 2")).toBeVisible();
  await expect(page.getByText(/Wersja 2/)).toBeVisible();
  await expectAccessible(page);

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Eksportuj CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^bom-.*\.csv$/);
  await expect(page.getByText("Wyeksportowano CSV")).toBeVisible();

  await page.getByRole("link", { name: "Log audytu" }).click();
  await expect(page.getByText("bom.item_updated")).toBeVisible();
  await page.getByRole("button", { name: "Sprawdź integralność" }).click();
  await expect(page.getByText(/Łańcuch audytu jest nienaruszony/)).toBeVisible();
  await expectAccessible(page);
});
