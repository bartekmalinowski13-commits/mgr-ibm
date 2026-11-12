import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";
import { AuthCallbackScreen } from "./AuthCallbackScreen";

const navigate = vi.fn();
const signIn = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => navigate,
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
}));
vi.mock("../lib/session", () => ({ useSession: () => ({ signIn }) }));
vi.mock("../lib/oidc", async (orig) => ({
  ...(await orig<typeof import("../lib/oidc")>()),
  authConfig: async () => ({ mode: "supabase", url: "https://p.supabase.co", anonKey: "a" }),
}));

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  navigate.mockReset();
  signIn.mockReset();
  window.history.replaceState(null, "", "/");
});

describe("callback in supabase mode", () => {
  it("shows a friendly message and a way back when the provider returned an error", async () => {
    window.history.replaceState(null, "", "/auth/callback?error=access_denied&error_description=x");
    render(<AuthCallbackScreen />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("access_denied");
    expect(screen.getByRole("link").getAttribute("href")).toBe("/login");
    expect(signIn).not.toHaveBeenCalled();
  });

  it("fails closed when the stored verifier is missing", async () => {
    window.history.replaceState(null, "", "/auth/callback?code=abc");
    const fetchFn = vi.fn();
    vi.stubGlobal("fetch", fetchFn);
    render(<AuthCallbackScreen />);
    await screen.findByRole("alert");
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("signs in after a successful exchange", async () => {
    sessionStorage.setItem("bomagent.social.verifier", "ver");
    window.history.replaceState(null, "", "/auth/callback?code=abc");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ access_token: "a.b.c", user: { id: "u" } }))),
    );
    render(<AuthCallbackScreen />);
    await waitFor(() => expect(signIn).toHaveBeenCalled());
    expect(navigate).toHaveBeenCalledWith({ to: "/start", replace: true });
  });
});
