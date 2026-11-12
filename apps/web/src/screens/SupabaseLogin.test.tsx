import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";
import { SessionProvider } from "../lib/session";
import type { SupabaseConfig } from "../lib/supabase";
import { SupabaseLogin } from "./SupabaseLogin";

const start = vi.fn();
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("../lib/supabase", async (orig) => ({
  ...(await orig<typeof import("../lib/supabase")>()),
  startSocialLogin: (...a: unknown[]) => start(...a),
}));

const base: SupabaseConfig = { mode: "supabase", url: "https://p.supabase.co", anonKey: "a" };

function view(cfg: SupabaseConfig) {
  return render(
    <SessionProvider>
      <SupabaseLogin cfg={cfg} />
    </SessionProvider>,
  );
}

const social = (b: HTMLElement) => /Google|Microsoft|Apple/.test(b.textContent ?? "");

afterEach(() => {
  cleanup();
  start.mockReset();
});

describe("social buttons", () => {
  it("are hidden when the config lists no providers", () => {
    view(base);
    expect(screen.getAllByRole("button").filter(social)).toHaveLength(0);
  });

  it("show only the configured providers, in order, as real buttons", () => {
    view({ ...base, providers: ["azure", "google", "nope"] });
    const buttons = screen.getAllByRole("button").filter(social);
    expect(buttons).toHaveLength(2);
    expect(buttons[0]?.textContent).toMatch(/Microsoft/);
    expect(buttons[1]?.textContent).toMatch(/Google/);
  });

  it("start the flow for the clicked provider", () => {
    view({ ...base, providers: ["google", "apple"] });
    fireEvent.click(screen.getAllByRole("button").filter(social)[1] as HTMLElement);
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ url: base.url }), "apple");
  });
});
