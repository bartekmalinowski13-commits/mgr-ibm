import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

test("create organisation -> invite a member -> member joins -> switch organisations", async ({
  browser,
}) => {
  const id = unique();
  const owner = await (await browser.newContext()).newPage();
  await signIn(owner, `owner-${id}@medtech.example`, "Olga");
  await createOrganisation(owner, `Alfa ${id}`);

  await owner.getByRole("link", { name: "Ustawienia" }).click();
  await expectAccessible(owner);
  const email = `eng-${id}@medtech.example`;
  await owner.getByLabel("E-mail").fill(email);
  await owner.getByLabel("Rola").last().selectOption("engineer");
  await owner.getByRole("button", { name: "Utwórz zaproszenie" }).click();
  const token = (await owner.getByTestId("secret").textContent())?.trim() ?? "";
  expect(token.length).toBeGreaterThan(20);
  await expect(owner.getByText(email)).toBeVisible();

  await owner.getByRole("tab", { name: "Klucze API" }).click();
  await owner.getByLabel("Nazwa klucza").fill("CI");
  await owner.getByRole("button", { name: "Utwórz klucz" }).click();
  await expect(owner.getByTestId("secret")).toContainText("bomk_");
  await owner.getByRole("tab", { name: "Zużycie i limity" }).click();
  await expect(owner.getByText("Koszt LLM")).toBeVisible();
  await expectAccessible(owner);

  const member = await (await browser.newContext()).newPage();
  await signIn(member, email, "Ewa");
  await member.waitForURL("**/onboarding");
  await member.getByLabel("Kod zaproszenia").fill(token);
  await member.getByRole("button", { name: "Dołącz do organizacji" }).click();
  await member.waitForURL("**/start");
  await expect(member.getByRole("button", { name: "Przełącz organizację" })).toContainText(
    `Alfa ${id}`,
  );

  // a second organisation of her own, then switch back
  await member.getByRole("button", { name: "Przełącz organizację" }).click();
  await member.getByRole("menuitem", { name: "Załóż nową organizację" }).click();
  await createOrganisation(member, `Beta ${id}`);
  await member.getByRole("button", { name: "Przełącz organizację" }).click();
  await member.getByRole("menuitem", { name: `Alfa ${id}` }).click();
  await expect(member.getByRole("button", { name: "Przełącz organizację" })).toContainText(
    `Alfa ${id}`,
  );
  await expect(member.getByRole("button", { name: "Przełącz organizację" })).toContainText(
    "Inżynier",
  );
});
