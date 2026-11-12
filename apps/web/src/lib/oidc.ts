/**
 * Sign-in with the OIDC hosted login (Amazon Cognito in AWS, ADR-0005): authorization
 * code flow with PKCE for a public client (no secret in the browser). The ID token is
 * sent to the API as the bearer token; the API verifies issuer, audience, expiry and
 * the verified e-mail. Locally `/config.json` is absent and the mock IdP is used.
 */
import type { Session } from "./session";

export type AuthConfig =
  | { mode: "local" }
  | { mode: "oidc"; domain: string; clientId: string; redirectUri: string; logoutUri?: string }
  | { mode: "supabase"; url: string; anonKey: string };

const VERIFIER = "bomagent.pkce.verifier";
const STATE = "bomagent.pkce.state";

let cached: Promise<AuthConfig> | undefined;

/** `/config.json` is written next to the SPA at deployment (no build-time secrets). */
export function authConfig(): Promise<AuthConfig> {
  cached ??= fetch("/config.json")
    .then(async (r) => (r.ok ? ((await r.json()) as { auth?: AuthConfig }).auth : undefined))
    .then((auth) => auth ?? { mode: "local" as const })
    .catch(() => ({ mode: "local" as const }));
  return cached;
}

function base64Url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(bytes = 32): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(bytes)));
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

export function authorizeUrl(
  cfg: Extract<AuthConfig, { mode: "oidc" }>,
  challenge: string,
  state: string,
  identityProvider?: string,
): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: cfg.clientId,
    redirect_uri: cfg.redirectUri,
    scope: "openid email profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state,
  });
  // Cognito skips its own page and goes to the organisation's SAML / OIDC provider
  if (identityProvider) params.set("identity_provider", identityProvider);
  return `${cfg.domain}/oauth2/authorize?${params}`;
}

export function decodeIdToken(token: string): { sub: string; email: string; name: string } {
  const part = token.split(".")[1] ?? "";
  const json = atob(
    part
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(part.length / 4) * 4, "="),
  );
  const claims = JSON.parse(
    new TextDecoder().decode(Uint8Array.from(json, (c) => c.charCodeAt(0))),
  ) as Record<string, unknown>;
  return {
    sub: String(claims.sub ?? ""),
    email: String(claims.email ?? ""),
    name: String(claims.name ?? claims.given_name ?? ""),
  };
}

/** Redirects the browser to the hosted login. */
/** Identity provider of the e-mail's organisation, if it uses single sign-on. */
export async function discoverSso(email: string): Promise<string | undefined> {
  const resp = await fetch(`/v1/sso/discover?${new URLSearchParams({ email })}`);
  if (!resp.ok) return undefined;
  const body = (await resp.json()) as { sso: boolean; provider?: string | null };
  return body.sso && body.provider ? body.provider : undefined;
}

export async function startLogin(
  cfg: Extract<AuthConfig, { mode: "oidc" }>,
  identityProvider?: string,
): Promise<void> {
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem(VERIFIER, verifier);
  sessionStorage.setItem(STATE, state);
  window.location.assign(authorizeUrl(cfg, await pkceChallenge(verifier), state, identityProvider));
}

/** Exchanges the authorization code for tokens; rejects a mismatched state (CSRF). */
export async function completeLogin(
  cfg: Extract<AuthConfig, { mode: "oidc" }>,
  search: URLSearchParams,
): Promise<Session> {
  const verifier = sessionStorage.getItem(VERIFIER);
  const expected = sessionStorage.getItem(STATE);
  sessionStorage.removeItem(VERIFIER);
  sessionStorage.removeItem(STATE);
  const code = search.get("code");
  if (!code || !verifier || !expected || search.get("state") !== expected) {
    throw new Error("sign-in response is invalid or expired");
  }
  const resp = await fetch(`${cfg.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: cfg.clientId,
      code,
      redirect_uri: cfg.redirectUri,
      code_verifier: verifier,
    }),
  });
  if (!resp.ok) throw new Error(`token exchange failed (${resp.status})`);
  const { id_token: token } = (await resp.json()) as { id_token: string };
  return { token, ...decodeIdToken(token) };
}

export function logoutUrl(cfg: Extract<AuthConfig, { mode: "oidc" }>): string {
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    logout_uri: cfg.logoutUri ?? new URL("/login", cfg.redirectUri).toString(),
  });
  return `${cfg.domain}/logout?${params}`;
}
