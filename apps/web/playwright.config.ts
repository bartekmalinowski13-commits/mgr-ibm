import { existsSync, readFileSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

/* Two modes:
 * - default: UI with the in-memory mock API (no backend) – smoke, a11y and user flows;
 * - E2E_STACK=1: UI over HTTP against a running stack (docker compose or
 *   tools/dev/native_stack.py), token from .native-stack/token or E2E_TOKEN. */
const stack = Boolean(process.env.E2E_STACK);
const port = stack ? 5181 : 5179;
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${port}`;
const tokenFile = new URL("../../.native-stack/token", import.meta.url);
const token =
  process.env.E2E_TOKEN ?? (existsSync(tokenFile) ? readFileSync(tokenFile, "utf8").trim() : "");

export default defineConfig({
  testDir: "./e2e",
  timeout: stack ? 90_000 : 30_000,
  fullyParallel: !stack,
  reporter: process.env.CI ? "github" : "list",
  ...(stack ? { testMatch: /stack\.spec\.ts/ } : { testIgnore: /stack\.spec\.ts/ }),
  use: {
    baseURL,
    locale: "pl-PL",
    trace: "retain-on-failure",
    // CI installs Playwright's Chromium; locally/cloud sessions may only have system Chrome
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    ...(stack ? [] : [{ name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /smoke/ }]),
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm exec vite --port ${port} --strictPort`,
        env: stack ? { VITE_API_MODE: "http", VITE_DEV_TOKEN: token } : { VITE_API_MODE: "mock" },
        url: baseURL,
        reuseExistingServer: !process.env.CI,
      },
});
