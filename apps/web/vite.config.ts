import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.BOMAGENT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/v1": { target: api, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/v1": { target: api, changeOrigin: false } } },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
