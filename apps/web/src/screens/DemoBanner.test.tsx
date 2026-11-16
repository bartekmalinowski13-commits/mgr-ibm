import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";
import i18n from "../lib/i18n";
import { DemoBanner } from "./DemoBanner";

const runtime = vi.fn();
vi.mock("../lib/oidc", async (orig) => ({
  ...(await orig<typeof import("../lib/oidc")>()),
  runtimeInfo: () => runtime(),
}));

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DemoBanner />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  runtime.mockReset();
});

describe("demo banner", () => {
  it("is shown, in the UI language, on a demo deployment", async () => {
    runtime.mockResolvedValue({ mode: "demo", llm: "fake", embeddings: "fake" });
    await i18n.changeLanguage("en");
    view();
    expect((await screen.findByRole("status")).textContent).toMatch(/Demo mode/);
    cleanup();
    await i18n.changeLanguage("pl");
    view();
    expect((await screen.findByRole("status")).textContent).toMatch(/Tryb demo/);
  });

  it("is absent on a live deployment", async () => {
    runtime.mockResolvedValue({ mode: "live" });
    view();
    await vi.waitFor(() => expect(runtime).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });
});
