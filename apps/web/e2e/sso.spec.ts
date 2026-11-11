import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

test("verify a domain -> configure SAML -> a colleague signs in through SSO and joins", async ({
  browser,
}) => {
  const id = unique();
  const domain = `sso-${id}.example`;
  const owner = await (await browser.newContext()).newPage();
  await signIn(owner, `owner@${domain}`, "Olga");
  await createOrganisation(owner, `SSO ${id}`);
  await owner.getByRole("link", { name: "Ustawienia" }).click();
  await owner.getByRole("tab", { name: "SSO" }).click();

  await owner.getByLabel("Domena").fill(domain);
  await owner.getByRole("button", { name: "Dodaj domenę" }).click();
  const record = owner.getByText(`_bomagent-verify.${domain}`);
  await expect(record).toBeVisible();
  const value =
    (await owner.locator("code", { hasText: "bomagent-verification=" }).textContent()) ?? "";
  // local stack: the test plays the customer's DNS
  const dns = await owner.request.post("/v1/sso/dev/dns", {
    data: { name: `_bomagent-verify.${domain}`, value: value.trim() },
  });
  expect(dns.status()).toBe(204);
  await owner.getByRole("button", { name: "Weryfikuj" }).click();
  await expect(owner.getByText("Zweryfikowana", { exact: true })).toBeVisible();

  await owner.getByLabel("Adres metadanych SAML").fill("https://idp.example/metadata.xml");
  await owner.getByLabel("Rola nowych członków").selectOption("engineer");
  await owner.getByRole("button", { name: "Zapisz" }).click();
  await expect(owner.getByRole("status").filter({ hasText: "Aktywny" })).toBeVisible();
  await expectAccessible(owner);

  // a colleague from the verified domain: discovery -> identity provider -> member
  const colleague = await (await browser.newContext()).newPage();
  await signIn(colleague, `eve@${domain}`, "Ewa");
  await colleague.waitForURL("**/start");
  await expect(colleague.getByRole("button", { name: "Przełącz organizację" })).toContainText(
    `SSO ${id}`,
  );
});
