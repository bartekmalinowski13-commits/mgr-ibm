// Dev helper: screenshots of every screen for design review (not part of the test suite).
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://127.0.0.1:5179";
const out = process.argv[3] ?? "/tmp/shots";
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const shot = async (name) => page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
await page.goto(base);
await page.waitForTimeout(900);
await shot("01-start");
await page.getByRole("link", { name: "Przebiegi" }).first().click();
await page.waitForTimeout(400);
await shot("02-runs");
await page
  .getByRole("link", { name: /Otwórz przebieg B/ })
  .first()
  .click();
await page.waitForTimeout(700);
await shot("03-run-b");
await page
  .getByRole("button", { name: /J1/ })
  .first()
  .click()
  .catch(() => {});
await page.waitForTimeout(400);
await shot("04-run-b-sheet");
await page.keyboard.press("Escape");
await page.goto(`${base}/compare`);
await page.waitForTimeout(800);
await shot("05-compare");
await page.goto(`${base}/projects`);
await page.waitForTimeout(400);
await page
  .getByRole("link", { name: /Monitor EKG/ })
  .first()
  .click();
await page.waitForTimeout(500);
await shot("06-project");
await page.getByRole("button", { name: "Uruchom przebieg" }).first().click();
await page.waitForTimeout(400);
await shot("07-new-run");
await page.keyboard.press("Escape");
await page.goto(`${base}/audit`);
await page.waitForTimeout(400);
await shot("08-audit");
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(base);
await page.waitForTimeout(900);
await shot("09-start-mobile");
await browser.close();
