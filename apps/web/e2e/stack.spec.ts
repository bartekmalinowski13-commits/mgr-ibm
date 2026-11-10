import { readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

/* Full stack (E2E_STACK=1): real API, S3/SQS (moto), parser, agents with the simulated
 * model, kb-indexer. Exercises the HTTP client: presigned uploads, SSE, review, KB. */
const fixtures = new URL("../../../evals/fixtures/", import.meta.url).pathname;
const ecg = join(fixtures, "kicad", "ecg-frontend");

test("stack: KiCad upload → parse → run A + B → compare → review a line", async ({ page }) => {
  await page.goto("/projects");
  const name = `EKG stos ${Date.now()}`;
  await page.getByLabel("Nazwa projektu, np. Monitor EKG").fill(name);
  await page.getByRole("button", { name: "Utwórz projekt" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  const files = readdirSync(ecg)
    .filter((f) => f.endsWith(".kicad_sch") || f.endsWith(".kicad_pro"))
    .map((f) => join(ecg, f));
  await page.getByTestId("design-files").setInputFiles(files);
  await expect(page.getByText("Gotowy")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Uruchom przebieg" }).click();
  const dialog = page.getByRole("dialog", { name: "Nowy przebieg" });
  await dialog.getByLabel("Nazwa*").fill("Przegląd na stosie");
  await dialog.getByRole("button", { name: "Uruchom przebieg" }).click();

  await expect(page).toHaveURL(/\/compare\?a=.+&b=.+/);
  await expect(page.getByRole("row", { name: /Wywołania LLM/ })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: /B · hybryda/ }).click();
  const table = page.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(23);
  await table.getByRole("button", { name: "J1" }).click();
  const sheet = page.getByRole("dialog", { name: /Szczegóły pozycji/ });
  await sheet.getByLabel("MPN").fill("22-23-2041");
  await sheet.getByLabel("Uzasadnienie*").fill("złącze z magazynu");
  await sheet.getByRole("button", { name: "Zapisz poprawkę" }).click();
  await expect(page.getByText("Po przeglądzie · 1 poprawka")).toBeVisible();
});

test("stack: knowledge base document is uploaded and indexed", async ({ page }) => {
  await page.goto("/knowledge");
  await page.getByLabel("Tytuł").fill(`AD8232 ${Date.now()}`);
  await page.getByLabel("Producent").fill("Analog Devices");
  await page.getByTestId("kb-file").setInputFiles({
    name: `ad8232-${Date.now()}.md`,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# AD8232\nSingle-lead heart rate monitor front end. ${Date.now()}`),
  });
  const row = page.getByRole("row", { name: /AD8232 \d+/ });
  await expect(row).toContainText("Gotowy", { timeout: 30_000 });
});
