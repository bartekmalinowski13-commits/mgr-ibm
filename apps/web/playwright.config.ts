import { defineConfig, devices } from "@playwright/test";

/* E2E against the UI in mock-API mode (no backend). The full-stack E2E (docker compose)
 * runs the same specs with E2E_BASE_URL pointing at the stack. */
const port = 5179;
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  reporter: process.env.CI ? "github" : "list",
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
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /smoke/ },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm exec vite --port ${port} --strictPort`,
        env: { VITE_API_MODE: "mock" },
        url: baseURL,
        reuseExistingServer: !process.env.CI,
      },
});
