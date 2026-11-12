import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** WCAG 2.2 AA via axe: no violations on the current page (TESTING.md). */
export async function expectAccessible(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(
    result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" ")}`),
  ).toEqual([]);
}

export async function signIn(page: Page, email: string, name: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Imię").fill(name);
  await page.getByRole("button", { name: "Zaloguj się" }).click();
}

export async function createOrganisation(page: Page, name: string): Promise<void> {
  await page.waitForURL("**/onboarding");
  await page.getByLabel("Nazwa organizacji").fill(name);
  await page.getByRole("button", { name: "Utwórz organizację" }).click();
  await page.waitForURL("**/start");
}
