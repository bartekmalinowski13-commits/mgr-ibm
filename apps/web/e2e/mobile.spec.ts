import { expect, test } from "@playwright/test";
import { createOrganisation, expectAccessible, signIn, unique } from "./helpers";

// QA-04: the critical entry path at a phone viewport (iPhone 13 size, Chromium). Small and
// deterministic on purpose: sign in -> onboarding -> start page, with the WCAG check at each step.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

test("phone viewport: sign in -> create organisation -> start page", async ({ page }) => {
  const id = unique();
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Zaloguj się" })).toBeVisible();
  await expectAccessible(page);

  await signIn(page, `mobile-${id}@medtech.example`, "Marta");
  await createOrganisation(page, `Mobile ${id}`);
  await expect(page.getByRole("heading", { name: "Cześć, Marta" })).toBeVisible();
  await expectAccessible(page);
});
