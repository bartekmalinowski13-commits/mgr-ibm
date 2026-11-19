import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../lib/i18n";
import { ToastProvider } from "../lib/toast";
import pl from "../locales/pl.json";

const get = vi.fn();
const del = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("../lib/api", async (orig) => ({
  ...(await orig<typeof import("../lib/api")>()),
  api: {
    GET: (...a: unknown[]) => get(...a),
    DELETE: (...a: unknown[]) => del(...a),
    POST: (...a: unknown[]) => post(...a),
    PATCH: (...a: unknown[]) => patch(...a),
  },
}));
vi.mock("../lib/queries", () => ({
  useMe: () => ({
    isPending: false,
    data: { organizations: [{ org_id: "org", roles: ["owner"] }] },
  }),
  useUsage: () => ({ isPending: true }),
}));
vi.mock("../lib/session", () => ({
  useSession: () => ({ orgId: "org", session: { sub: "me" } }),
}));
vi.mock("../lib/oidc", () => ({ authConfig: async () => ({ mode: "local" }) }));

const { SettingsScreen } = await import("./SettingsScreen");

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const lists: Record<string, unknown> = {
  "/v1/members": {
    items: [
      { user_sub: "me", email: "me@x.eu", display_name: "Me", roles: ["owner"] },
      { user_sub: "u2", email: "ola@x.eu", display_name: "Ola", roles: ["engineer"] },
    ],
  },
  "/v1/invitations": {
    items: [{ id: "i1", email: "new@x.eu", roles: ["viewer"], expires_at: "2030-01-01" }],
  },
  "/v1/api-keys": {
    items: [{ id: "k1", name: "ci-bot", prefix: "bk_1", roles: ["viewer"], last_used_at: null }],
  },
};

const confirmSpy = vi.fn<(message?: string) => boolean>();

beforeEach(async () => {
  await i18n.changeLanguage("pl");
  for (const fn of [get, del, post, patch]) fn.mockReset();
  get.mockImplementation(async (path: string) => ok(lists[path]));
  del.mockResolvedValue({ response: new Response(null, { status: 204 }) });
  post.mockResolvedValue(ok({ key: "secret" }));
  patch.mockResolvedValue(ok({}));
  confirmSpy.mockReset();
  vi.stubGlobal("confirm", confirmSpy);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderScreen() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <SettingsScreen />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("destructive admin actions ask first (I-4)", () => {
  it("does not remove a member when the confirmation is declined", async () => {
    confirmSpy.mockReturnValue(false);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: pl.settings.removeMember }));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0]?.[0]).toContain("Ola");
    expect(del).not.toHaveBeenCalled();
  });

  it("removes the member once confirmed", async () => {
    confirmSpy.mockReturnValue(true);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: pl.settings.removeMember }));
    await waitFor(() => expect(del).toHaveBeenCalledTimes(1));
  });

  it("asks before changing a role and keeps it when declined", async () => {
    confirmSpy.mockReturnValue(false);
    renderScreen();
    await screen.findByText("ola@x.eu");
    const select = document.getElementById("role-u2") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "viewer" } });
    expect(confirmSpy.mock.calls[0]?.[0]).toContain("Ola");
    expect(select.value).toBe("engineer");
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(patch).not.toHaveBeenCalled();
  });

  it("asks before revoking an invitation and uses a past-tense toast", async () => {
    confirmSpy.mockReturnValue(true);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: pl.settings.revoke }));
    expect(confirmSpy.mock.calls[0]?.[0]).toContain("new@x.eu");
    expect(await screen.findByText(pl.settings.invitationRevoked)).toBeTruthy();
  });

  it.each([
    ["rotate", () => pl.settings.rotate, post],
    ["revoke", () => pl.settings.revoke, del],
  ])("asks before the %s of an API key, naming it", async (_n, label, endpoint) => {
    confirmSpy.mockReturnValue(false);
    renderScreen();
    fireEvent.click(await screen.findByRole("tab", { name: pl.settings.tabs.keys }));
    fireEvent.click(await screen.findByRole("button", { name: label() }));
    expect(confirmSpy.mock.calls[0]?.[0]).toContain("ci-bot");
    expect(endpoint).not.toHaveBeenCalled();
  });

  it("says the key was revoked, in the past tense", async () => {
    confirmSpy.mockReturnValue(true);
    renderScreen();
    fireEvent.click(await screen.findByRole("tab", { name: pl.settings.tabs.keys }));
    fireEvent.click(await screen.findByRole("button", { name: pl.settings.revoke }));
    expect(await screen.findByText(pl.settings.keyRevoked)).toBeTruthy();
  });
});
