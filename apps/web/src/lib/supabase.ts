/**
 * Sign-in with Supabase Auth (GoTrue) for the Supabase-hosted deployment variant. Plain
 * `fetch` against the REST endpoints, no SDK. The `anonKey` is public by design (data access
 * is governed by the API and RLS, not by this key). The access token is sent to the API as
 * the bearer token; it is refreshed with the refresh token shortly before expiry.
 * Passwords and tokens are never logged.
 */
import type { AuthConfig } from "./oidc";
import type { Session } from "./session";

export type SupabaseConfig = Extract<AuthConfig, { mode: "supabase" }>;

/** Refresh this long before the access token expires. */
export const REFRESH_MARGIN_MS = 60_000;

/** i18n keys (under `login.supabase.errors`) for failures of the Auth endpoints. */
export type SupabaseErrorKey =
  | "invalidCredentials"
  | "emailNotConfirmed"
  | "userExists"
  | "weakPassword"
  | "rateLimited"
  | "signupDisabled"
  | "network"
  | "unknown";

export class SupabaseAuthError extends Error {
  constructor(
    readonly key: SupabaseErrorKey,
    readonly status: number,
  ) {
    super(key);
    this.name = "SupabaseAuthError";
  }
}

interface GoTrueUser {
  id?: string;
  email?: string;
  user_metadata?: { full_name?: unknown } | null;
}

interface GoTrueSession {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  expires_at?: number;
  user?: GoTrueUser;
}

export function authRequest(
  cfg: SupabaseConfig,
  path: string,
  body: unknown,
  accessToken?: string,
): { url: string; init: RequestInit } {
  const headers: Record<string, string> = {
    apikey: cfg.anonKey,
    "Content-Type": "application/json",
  };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return {
    url: `${cfg.url.replace(/\/+$/, "")}/auth/v1/${path}`,
    init: { method: "POST", headers, body: JSON.stringify(body ?? {}) },
  };
}

/** Maps a GoTrue error response (`error_code` / `msg` / `error_description`) to a key. */
export function mapAuthError(status: number, body: unknown): SupabaseErrorKey {
  const b = (body ?? {}) as Record<string, unknown>;
  const code = String(b.error_code ?? b.code ?? "");
  const text = String(b.msg ?? b.message ?? b.error_description ?? "").toLowerCase();
  if (code === "invalid_credentials" || text.includes("invalid login credentials")) {
    return "invalidCredentials";
  }
  if (code === "email_not_confirmed" || text.includes("email not confirmed")) {
    return "emailNotConfirmed";
  }
  if (code === "user_already_exists" || code === "email_exists" || text.includes("already")) {
    return "userExists";
  }
  if (code === "weak_password" || text.includes("password should be")) return "weakPassword";
  if (code === "signup_disabled" || text.includes("signups not allowed")) return "signupDisabled";
  if (status === 429 || code.startsWith("over_") || text.includes("rate limit")) {
    return "rateLimited";
  }
  return "unknown";
}

async function post<T>(
  cfg: SupabaseConfig,
  path: string,
  body: unknown,
  accessToken?: string,
): Promise<T> {
  const { url, init } = authRequest(cfg, path, body, accessToken);
  let resp: Response;
  try {
    resp = await fetch(url, init);
  } catch {
    throw new SupabaseAuthError("network", 0);
  }
  const text = await resp.text();
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = {};
  }
  if (!resp.ok) throw new SupabaseAuthError(mapAuthError(resp.status, json), resp.status);
  return json as T;
}

function decodeClaims(token: string): Record<string, unknown> {
  try {
    const part = token.split(".")[1] ?? "";
    const b64 = part
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(part.length / 4) * 4, "=");
    const json = new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** Greeting name: `user_metadata.full_name`, else the e-mail. */
export function displayName(user: GoTrueUser | undefined, claims: Record<string, unknown>) {
  const meta = user?.user_metadata ?? (claims.user_metadata as GoTrueUser["user_metadata"]);
  const full = typeof meta?.full_name === "string" ? meta.full_name.trim() : "";
  return full || user?.email || String(claims.email ?? "");
}

export function toSession(data: GoTrueSession, now = Date.now()): Session {
  const claims = decodeClaims(data.access_token);
  const exp = data.expires_at ?? (typeof claims.exp === "number" ? claims.exp : undefined);
  const expiresAt = data.expires_in
    ? now + data.expires_in * 1000
    : exp
      ? exp * 1000
      : now + 3_600_000;
  return {
    token: data.access_token,
    sub: data.user?.id ?? String(claims.sub ?? ""),
    email: data.user?.email ?? String(claims.email ?? ""),
    name: displayName(data.user, claims),
    refreshToken: data.refresh_token,
    expiresAt,
  };
}

export async function signInWithPassword(
  cfg: SupabaseConfig,
  email: string,
  password: string,
): Promise<Session> {
  return toSession(
    await post<GoTrueSession>(cfg, "token?grant_type=password", { email, password }),
  );
}

/** Resolves a session when sign-up auto-confirms, else `"confirm"` (check your inbox). */
export async function signUp(
  cfg: SupabaseConfig,
  email: string,
  password: string,
  fullName: string,
): Promise<Session | "confirm"> {
  const data = await post<GoTrueSession>(cfg, "signup", {
    email,
    password,
    data: { full_name: fullName },
  });
  return data.access_token ? toSession(data) : "confirm";
}

export async function refreshSession(cfg: SupabaseConfig, refreshToken: string): Promise<Session> {
  return toSession(
    await post<GoTrueSession>(cfg, "token?grant_type=refresh_token", {
      refresh_token: refreshToken,
    }),
  );
}

export async function recoverPassword(cfg: SupabaseConfig, email: string): Promise<void> {
  await post(cfg, "recover", { email });
}

/** Best effort: revokes the refresh token on the server; local sign-out never waits on it. */
export async function signOutRemote(cfg: SupabaseConfig, accessToken: string): Promise<void> {
  try {
    await post(cfg, "logout", {}, accessToken);
  } catch {
    /* already signed out locally */
  }
}

/** Milliseconds until the session should be refreshed (0 = now). */
export function refreshDelay(expiresAt: number, now = Date.now()): number {
  return Math.max(0, expiresAt - REFRESH_MARGIN_MS - now);
}
