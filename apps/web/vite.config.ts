import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.BOMAGENT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/v1": { target: api, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/v1": { target: api, changeOrigin: false } } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      reporter: ["text-summary", "cobertura"],
      // No-drop gate: the measured coverage at the time the gate was added (rounded down).
      // TESTING.md's target for the frontend is 75 % lines - raise these as tests are added,
      // never lower them (docs/DECISIONS_LOG.md, 2026-11-19).
      thresholds: { lines: 49, statements: 48, functions: 45, branches: 42 },
    },
  },
});
