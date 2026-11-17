import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import {
  authorizeUrl,
  completeLogin,
  decodeIdToken,
  emailDomain,
  idTokenNonce,
  parseRuntime,
  pkceChallenge,
} from "./oidc";

describe("PKCE", () => {
  it("derives the S256 challenge: base64url(SHA-256(verifier)) without padding", async () => {
    const verifier = "dBjftJeZ4CVP-mJ92BqsN1grpgK0TA3Fq3OB2zCjydM";
    const expected = createHash("sha256").update(verifier).digest("base64url");
    const challenge = await pkceChallenge(verifier);
    expect(challenge).toBe(expected);
    expect(challenge).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("builds the hosted-login URL with code flow, S256 and state", () => {
    const url = new URL(
      authorizeUrl(
        {
          mode: "oidc",
          domain: "https://login.example",
          clientId: "abc",
          redirectUri: "https://app/auth/callback",
        },
        "challenge",
        "state-1",
      ),
    );
    expect(url.origin + url.pathname).toBe("https://login.example/oauth2/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      response_type: "code",
      client_id: "abc",
      redirect_uri: "https://app/auth/callback",
      scope: "openid email profile",
      code_challenge_method: "S256",
      code_challenge: "challenge",
      state: "state-1",
    });
  });

  it("sends the user straight to their organisation's identity provider", () => {
    const url = new URL(
      authorizeUrl(
        {
          mode: "oidc",
          domain: "https://login.example",
          clientId: "abc",
          redirectUri: "https://app/auth/callback",
        },
        "challenge",
        "state-1",
        "org-0123456789abcdef01234567",
      ),
    );
    expect(url.searchParams.get("identity_provider")).toBe("org-0123456789abcdef01234567");
  });

  it("reads profile claims from an ID token (verification happens in the API)", () => {
    const payload = btoa(JSON.stringify({ sub: "u-1", email: "ola@x.eu", name: "Ola" }))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    expect(decodeIdToken(`h.${payload}.s`)).toEqual({ sub: "u-1", email: "ola@x.eu", name: "Ola" });
  });
});

describe("runtime info from /config.json", () => {
  it("reports demo only when the deployment says so", () => {
    expect(parseRuntime({ mode: "demo", llm: "fake", embeddings: "fake" })).toEqual({
      mode: "demo",
      llm: "fake",
      embeddings: "fake",
    });
    expect(parseRuntime({ mode: "live" }).mode).toBe("live");
    expect(parseRuntime(undefined).mode).toBe("live"); // local dev: no config.json
  });
});

describe("sso discovery", () => {
  it("raises RateLimitedError on 429 instead of pretending the e-mail has no SSO", async () => {
    const { discoverSso, RateLimitedError } = await import("./oidc");
    const spy = vi.spyOn(globalThis, "fetch");
    spy.mockResolvedValueOnce(new Response("{}", { status: 429, headers: { "Retry-After": "7" } }));
    await expect(discoverSso("a@b.eu")).rejects.toMatchObject({ retryAfterS: 7 });
    spy.mockResolvedValueOnce(new Response("{}", { status: 429 }));
    await expect(discoverSso("a@b.eu")).rejects.toBeInstanceOf(RateLimitedError);
    spy.mockResolvedValueOnce(new Response(JSON.stringify({ sso: true, provider: "p" })));
    expect(await discoverSso("a@b.eu")).toBe("p");
    spy.mockRestore();
  });
});

describe("sso discovery sends the domain only", () => {
  it("extracts a plain lower-case domain from the address", () => {
    expect(emailDomain(" Ann@Clinic.Example ")).toBe("clinic.example");
    expect(emailDomain("a@b@c.eu")).toBe("c.eu");
    for (const bad of ["", "ann", "ann@", "ann@localhost", "ann@x y.eu", "@", "ann@.eu"]) {
      expect(emailDomain(bad)).toBeUndefined();
    }
  });

  it("POSTs {domain} and never puts the address in the URL or the body", async () => {
    const { discoverSso } = await import("./oidc");
    const spy = vi.spyOn(globalThis, "fetch");
    spy.mockResolvedValueOnce(new Response(JSON.stringify({ sso: false, provider: null })));
    expect(await discoverSso("ann@Clinic.Example")).toBeUndefined();
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/sso/discover");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ domain: "clinic.example" });
    expect(String(init.body)).not.toContain("ann");
    spy.mockRestore();
  });

  it("does not call the API for something that is not an address", async () => {
    const { discoverSso } = await import("./oidc");
    const spy = vi.spyOn(globalThis, "fetch");
    expect(await discoverSso("not-an-address")).toBeUndefined();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

const idToken = (claims: object) =>
  `h.${btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.s`;
const cfg = {
  mode: "oidc" as const,
  domain: "https://login.example",
  clientId: "abc",
  redirectUri: "https://app/auth/callback",
};

describe("nonce", () => {
  it("is added to the authorize URL only when given", () => {
    const url = new URL(authorizeUrl(cfg, "c", "s", undefined, "n-1"));
    expect(url.searchParams.get("nonce")).toBe("n-1");
    expect(new URL(authorizeUrl(cfg, "c", "s")).searchParams.has("nonce")).toBe(false);
  });

  it("reads the nonce claim as a string only", () => {
    expect(idTokenNonce(idToken({ nonce: "n-1" }))).toBe("n-1");
    expect(idTokenNonce(idToken({ nonce: 5 }))).toBe("");
    expect(idTokenNonce(idToken({}))).toBe("");
  });

  async function login(stored: Record<string, string>, claims: object, state = "st") {
    sessionStorage.clear();
    for (const [k, v] of Object.entries(stored)) sessionStorage.setItem(k, v);
    const spy = vi.spyOn(globalThis, "fetch");
    spy.mockResolvedValueOnce(new Response(JSON.stringify({ id_token: idToken(claims) })));
    try {
      return await completeLogin(cfg, new URLSearchParams({ code: "c", state }));
    } finally {
      spy.mockRestore();
    }
  }
  const saved = {
    "bomagent.pkce.verifier": "v",
    "bomagent.pkce.state": "st",
    "bomagent.pkce.nonce": "n-1",
  };

  it("accepts an ID token carrying the nonce that was sent", async () => {
    const session = await login(saved, { sub: "u", email: "a@b.eu", nonce: "n-1" });
    expect(session.sub).toBe("u");
    expect(sessionStorage.getItem("bomagent.pkce.nonce")).toBeNull();
  });

  it("rejects a missing or different nonce, and a missing stored nonce", async () => {
    await expect(login(saved, { sub: "u", nonce: "other" })).rejects.toThrow(/invalid/);
    await expect(login(saved, { sub: "u" })).rejects.toThrow(/invalid/);
    const { "bomagent.pkce.nonce": _drop, ...noNonce } = saved;
    await expect(login(noNonce, { sub: "u", nonce: "n-1" })).rejects.toThrow(/invalid/);
  });

  it("still rejects a state mismatch", async () => {
    await expect(login(saved, { sub: "u", nonce: "n-1" }, "evil")).rejects.toThrow(/invalid/);
  });
});
