import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pkceChallenge } from "./oidc";
import {
  completeSocialLogin,
  enabledProviders,
  parseAuthReturn,
  type SupabaseConfig,
  socialAuthorizeUrl,
  startSocialLogin,
  updatePassword,
} from "./supabase";

const cfg: SupabaseConfig = { mode: "supabase", url: "https://p.supabase.co/", anonKey: "anon" };

function jwt(claims: object): string {
  const enc = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256" })}.${enc(claims)}.sig`;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("PKCE challenge (RFC 7636 appendix B)", () => {
  it("matches the published test vector", async () => {
    expect(await pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });
});

describe("authorize URL", () => {
  it("builds the Supabase authorize URL with S256 challenge and callback", () => {
    const url = new URL(socialAuthorizeUrl(cfg, "google", "https://app.example", "chal"));
    expect(url.origin + url.pathname).toBe("https://p.supabase.co/auth/v1/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      provider: "google",
      redirect_to: "https://app.example/auth/callback",
      code_challenge: "chal",
      code_challenge_method: "s256",
    });
  });

  it("requests the e-mail scope for the Microsoft (azure) provider only", () => {
    const azure = new URL(socialAuthorizeUrl(cfg, "azure", "https://a", "c"));
    expect(azure.searchParams.get("scopes")).toBe("email");
    const apple = new URL(socialAuthorizeUrl(cfg, "apple", "https://a", "c"));
    expect(apple.searchParams.has("scopes")).toBe(false);
  });
});

describe("startSocialLogin", () => {
  it("stores verifier and provider, then redirects to the authorize URL", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { origin: "https://app.example", assign });
    await startSocialLogin(cfg, "apple");
    const verifier = sessionStorage.getItem("bomagent.social.verifier") ?? "";
    expect(verifier).toMatch(/^[A-Za-z0-9_-]{43,128}$/);
    expect(sessionStorage.getItem("bomagent.social.provider")).toBe("apple");
    const url = new URL(String(assign.mock.calls[0]?.[0]));
    expect(url.searchParams.get("code_challenge")).toBe(await pkceChallenge(verifier));
    expect(url.searchParams.get("redirect_to")).toBe("https://app.example/auth/callback");
  });
});

describe("completeSocialLogin", () => {
  it("exchanges the code with the stored verifier and clears it", async () => {
    sessionStorage.setItem("bomagent.social.verifier", "ver");
    sessionStorage.setItem("bomagent.social.provider", "google");
    const access = jwt({ sub: "u1", email: "a@b.pl" });
    const fn = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            access_token: access,
            refresh_token: "r",
            expires_in: 3600,
            user: { id: "u1", email: "a@b.pl", user_metadata: { full_name: "Ada" } },
          }),
        ),
    );
    vi.stubGlobal("fetch", fn);
    const s = await completeSocialLogin(cfg, "the-code");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://p.supabase.co/auth/v1/token?grant_type=pkce");
    expect(JSON.parse(String(init.body))).toEqual({ auth_code: "the-code", code_verifier: "ver" });
    expect(s).toMatchObject({ token: access, sub: "u1", name: "Ada", refreshToken: "r" });
    expect(sessionStorage.getItem("bomagent.social.verifier")).toBeNull();
  });

  it("fails closed without a stored verifier and never calls the network", async () => {
    const fn = vi.fn();
    vi.stubGlobal("fetch", fn);
    await expect(completeSocialLogin(cfg, "code")).rejects.toMatchObject({ key: "socialInvalid" });
    expect(fn).not.toHaveBeenCalled();
  });

  it("fails closed without a code", async () => {
    sessionStorage.setItem("bomagent.social.verifier", "ver");
    await expect(completeSocialLogin(cfg, null)).rejects.toMatchObject({ key: "socialInvalid" });
    expect(sessionStorage.getItem("bomagent.social.verifier")).toBeNull();
  });

  it("surfaces a rejected exchange as an auth error and still clears the verifier", async () => {
    sessionStorage.setItem("bomagent.social.verifier", "ver");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ msg: "bad" }), { status: 400 })),
    );
    await expect(completeSocialLogin(cfg, "code")).rejects.toMatchObject({ status: 400 });
    expect(sessionStorage.getItem("bomagent.social.verifier")).toBeNull();
  });
});

describe("parseAuthReturn", () => {
  it("reads a code from the query", () => {
    expect(parseAuthReturn("?code=abc", "")).toEqual({ kind: "code", code: "abc" });
  });
  it("reads errors from the query or the fragment", () => {
    expect(parseAuthReturn("?error=access_denied&error_description=No", "")).toEqual({
      kind: "error",
      reason: "denied",
    });
    expect(parseAuthReturn("", "#error=server_error&error_code=x")).toEqual({
      kind: "error",
      reason: "failed",
    });
    expect(parseAuthReturn("", "#error=access_denied&error_code=otp_expired")).toEqual({
      kind: "error",
      reason: "expired",
    });
  });
  it("recognises a recovery fragment and a confirmation fragment", () => {
    expect(parseAuthReturn("", "#access_token=T&refresh_token=R&type=recovery")).toEqual({
      kind: "recovery",
      accessToken: "T",
    });
    expect(parseAuthReturn("", "#access_token=T&type=signup")).toEqual({ kind: "confirmed" });
  });
  it("returns none for anything else", () => {
    expect(parseAuthReturn("", "")).toEqual({ kind: "none" });
    expect(parseAuthReturn("", "#section")).toEqual({ kind: "none" });
  });
});

describe("enabledProviders", () => {
  it("keeps known providers in order and ignores the rest", () => {
    expect(enabledProviders(["apple", "x", "google", "google"])).toEqual(["apple", "google"]);
    expect(enabledProviders(undefined)).toEqual([]);
  });
});

describe("updatePassword", () => {
  it("PUTs the new password with the recovery token as bearer", async () => {
    const fn = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fn);
    await updatePassword(cfg, "rec-token", "newpassword1");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://p.supabase.co/auth/v1/user");
    expect(init.method).toBe("PUT");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer rec-token");
    expect(JSON.parse(String(init.body))).toEqual({ password: "newpassword1" });
  });
});
