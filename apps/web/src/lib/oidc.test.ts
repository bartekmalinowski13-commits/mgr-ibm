import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { authorizeUrl, decodeIdToken, parseRuntime, pkceChallenge } from "./oidc";

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
