import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authRequest,
  mapAuthError,
  recoverPassword,
  refreshDelay,
  refreshSession,
  type SupabaseConfig,
  signInWithPassword,
  signOutRemote,
  signUp,
} from "./supabase";

const cfg: SupabaseConfig = { mode: "supabase", url: "https://p.supabase.co/", anonKey: "anon" };

function jwt(claims: object): string {
  const enc = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${enc({ alg: "HS256" })}.${enc(claims)}.sig`;
}

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("request building", () => {
  it("sends the public apikey, JSON content type and normalises the base URL", () => {
    const { url, init } = authRequest(cfg, "token?grant_type=password", { a: 1 });
    expect(url).toBe("https://p.supabase.co/auth/v1/token?grant_type=password");
    expect(init.headers).toEqual({ apikey: "anon", "Content-Type": "application/json" });
  });

  it("password sign-in posts e-mail and password", async () => {
    const access = jwt({ sub: "u1", email: "a@b.pl", exp: 9_999_999_999 });
    const fn = mockFetch(200, {
      access_token: access,
      refresh_token: "r1",
      expires_in: 3600,
      user: { id: "u1", email: "a@b.pl", user_metadata: { full_name: "Ada Lovelace" } },
    });
    const s = await signInWithPassword(cfg, "a@b.pl", "pw");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://p.supabase.co/auth/v1/token?grant_type=password");
    expect(JSON.parse(String(init.body))).toEqual({ email: "a@b.pl", password: "pw" });
    expect(s).toMatchObject({
      token: access,
      sub: "u1",
      email: "a@b.pl",
      name: "Ada Lovelace",
      refreshToken: "r1",
    });
  });

  it("sign-up sends full_name as user data; no token means confirmation is required", async () => {
    const fn = mockFetch(200, { id: "u1", email: "a@b.pl" });
    expect(await signUp(cfg, "a@b.pl", "pw12345678", "Ada")).toBe("confirm");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://p.supabase.co/auth/v1/signup");
    expect(JSON.parse(String(init.body))).toEqual({
      email: "a@b.pl",
      password: "pw12345678",
      data: { full_name: "Ada" },
    });
  });

  it("refresh, recover and logout hit their endpoints; logout carries the access token", async () => {
    const fn = mockFetch(200, {
      access_token: jwt({ sub: "u1", email: "a@b.pl" }),
      refresh_token: "r2",
      expires_in: 100,
    });
    await refreshSession(cfg, "r1");
    await recoverPassword(cfg, "a@b.pl");
    await signOutRemote(cfg, "tok");
    const calls = fn.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map((c) => c[0])).toEqual([
      "https://p.supabase.co/auth/v1/token?grant_type=refresh_token",
      "https://p.supabase.co/auth/v1/recover",
      "https://p.supabase.co/auth/v1/logout",
    ]);
    expect(JSON.parse(String(calls[0]?.[1].body))).toEqual({ refresh_token: "r1" });
    expect(((calls[2]?.[1].headers ?? {}) as Record<string, string>).Authorization).toBe(
      "Bearer tok",
    );
  });
});

describe("session mapping", () => {
  it("falls back to the e-mail for the name and to the JWT exp for expiry", async () => {
    mockFetch(200, {
      access_token: jwt({ sub: "u9", email: "x@y.pl", exp: 2_000_000_000 }),
      refresh_token: "r",
    });
    const s = await signInWithPassword(cfg, "x@y.pl", "pw");
    expect(s.name).toBe("x@y.pl");
    expect(s.expiresAt).toBe(2_000_000_000_000);
  });

  it("uses user_metadata.full_name from the JWT when no user object is returned", async () => {
    mockFetch(200, {
      access_token: jwt({ sub: "u9", email: "x@y.pl", user_metadata: { full_name: "Zed" } }),
      refresh_token: "r",
      expires_in: 60,
    });
    expect((await signInWithPassword(cfg, "x@y.pl", "pw")).name).toBe("Zed");
  });
});

describe("refresh timing", () => {
  it("refreshes one minute before expiry, immediately when already due", () => {
    expect(refreshDelay(1_000_000 + 3_600_000, 1_000_000)).toBe(3_540_000);
    expect(refreshDelay(1_030_000, 1_000_000)).toBe(0);
    expect(refreshDelay(900_000, 1_000_000)).toBe(0);
  });
});

describe("error mapping", () => {
  it.each([
    [
      400,
      { error_code: "invalid_credentials", msg: "Invalid login credentials" },
      "invalidCredentials",
    ],
    [400, { msg: "Invalid login credentials" }, "invalidCredentials"],
    [400, { error_code: "email_not_confirmed", msg: "Email not confirmed" }, "emailNotConfirmed"],
    [422, { error_code: "user_already_exists" }, "userExists"],
    [422, { error_code: "weak_password", msg: "Password should be at least 8" }, "weakPassword"],
    [422, { error_code: "signup_disabled" }, "signupDisabled"],
    [429, { error_code: "over_email_send_rate_limit" }, "rateLimited"],
    [500, {}, "unknown"],
  ])("%s %j -> %s", (status, body, key) => {
    expect(mapAuthError(status, body)).toBe(key);
  });

  it("rejects with a mapped key and never leaks the response text", async () => {
    mockFetch(400, { error_code: "invalid_credentials", msg: "secret-detail" });
    await expect(signInWithPassword(cfg, "a@b.pl", "pw")).rejects.toMatchObject({
      key: "invalidCredentials",
      message: "invalidCredentials",
    });
  });

  it("maps a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    await expect(signInWithPassword(cfg, "a@b.pl", "pw")).rejects.toMatchObject({
      key: "network",
    });
  });
});
