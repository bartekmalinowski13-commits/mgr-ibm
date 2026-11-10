import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against a running API on :8000 - the compose stack in CI (`just up-core`) or
 * `uv run python tools/devstack.py` locally. Vite serves the app and proxies /v1.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    locale: "pl-PL",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm exec vite --port 5173 --strictPort",
    url: "http://127.0.0.1:5173/login",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
