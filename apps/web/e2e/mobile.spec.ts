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

test("phone viewport: the navigation drawer works from the keyboard", async ({ page }) => {
  const id = unique();
  await page.goto("/login");
  await signIn(page, `drawer-${id}@medtech.example`, "Marta");
  await createOrganisation(page, `Drawer ${id}`);
  // located by attribute: while the modal drawer is open the page behind is aria-hidden
  const trigger = page.locator('header button[aria-haspopup="dialog"]');
  await expect(trigger).toHaveAttribute("aria-label", "Nawigacja główna");
  await trigger.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: "Nawigacja główna" });
  await expect(drawer).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expectAccessible(page);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();
});
