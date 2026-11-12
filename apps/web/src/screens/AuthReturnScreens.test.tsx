import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../lib/i18n";
import { stashAuthReturn } from "../lib/authReturn";
import { EmailConfirmedScreen, ResetPasswordScreen } from "./AuthReturnScreens";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
}));
vi.mock("../lib/oidc", async (orig) => ({
  ...(await orig<typeof import("../lib/oidc")>()),
  authConfig: async () => ({ mode: "supabase", url: "https://p.supabase.co", anonKey: "a" }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  stashAuthReturn({ kind: "none" });
});

describe("ResetPasswordScreen", () => {
  it("without a recovery token offers a way back", () => {
    render(<ResetPasswordScreen />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/login");
  });

  it("sets the new password with the recovery token and confirms", async () => {
    stashAuthReturn({ kind: "recovery", accessToken: "rec" });
    const fn = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fn);
    render(<ResetPasswordScreen />);
    fireEvent.change(document.querySelector("input") as HTMLInputElement, {
      target: { value: "newpassword1" },
    });
    fireEvent.submit(document.querySelector("form") as HTMLFormElement);
    await waitFor(() => expect(fn).toHaveBeenCalled());
    const init = (fn.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer rec");
    await screen.findByRole("status");
  });
});

describe("EmailConfirmedScreen", () => {
  it("links to sign in", () => {
    render(<EmailConfirmedScreen />);
    expect(screen.getByRole("link").getAttribute("href")).toBe("/login");
  });
});
