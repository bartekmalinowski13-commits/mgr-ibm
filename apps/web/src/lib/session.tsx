/**
 * Session: OIDC access token + active organisation.
 *
 * Locally (and in E2E) the token comes from the API's mock IdP (`/v1/dev/token`); in AWS
 * the hosted Cognito login (PKCE) fills the same slot (M6). The token lives in
 * sessionStorage only (cleared with the tab), the chosen organisation in localStorage.
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { authConfig } from "./oidc";
import { refreshDelay, refreshSession } from "./supabase";

export interface Session {
  token: string;
  sub: string;
  email: string;
  name: string;
  /** Supabase mode only: refresh token and access-token expiry (epoch ms). */
  refreshToken?: string;
  expiresAt?: number;
}

const SESSION_KEY = "bomagent.session";
const orgKey = (sub: string) => `bomagent.org.${sub}`;

/** Read by the API client on every request (module-level, outside React). */
export const auth = { token: "", orgId: undefined as string | undefined };

function read<T>(storage: Storage, key: string): T | null {
  try {
    const raw = storage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(storage: Storage, key: string, value: unknown): void {
  try {
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable (private mode): the session lasts until reload */
  }
}

interface SessionState {
  session: Session | null;
  orgId: string | undefined;
  signIn: (session: Session) => void;
  signOut: () => void;
  selectOrg: (orgId: string | undefined) => void;
}

const Ctx = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() =>
    read<Session>(sessionStorage, SESSION_KEY),
  );
  const [orgId, setOrgId] = useState<string | undefined>(() =>
    session ? (read<string>(localStorage, orgKey(session.sub)) ?? undefined) : undefined,
  );
  auth.token = session?.token ?? "";
  auth.orgId = orgId;

  const signIn = useCallback((next: Session) => {
    write(sessionStorage, SESSION_KEY, next);
    setSession(next);
    setOrgId(read<string>(localStorage, orgKey(next.sub)) ?? undefined);
  }, []);
  const signOut = useCallback(() => {
    write(sessionStorage, SESSION_KEY, null);
    setSession(null);
    setOrgId(undefined);
  }, []);
  // Supabase mode: swap the access token for a fresh one shortly before it expires; when the
  // refresh fails (revoked or expired refresh token) the user is signed out.
  const { refreshToken, expiresAt } = session ?? {};
  useEffect(() => {
    if (!refreshToken || !expiresAt) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      void authConfig().then(async (cfg) => {
        if (cfg.mode !== "supabase") return;
        try {
          const next = await refreshSession(cfg, refreshToken);
          if (cancelled) return;
          write(sessionStorage, SESSION_KEY, next);
          setSession(next);
        } catch {
          if (!cancelled) signOut();
        }
      });
    }, refreshDelay(expiresAt));
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [refreshToken, expiresAt, signOut]);
  const selectOrg = useCallback(
    (next: string | undefined) => {
      if (session) write(localStorage, orgKey(session.sub), next ?? null);
      auth.orgId = next;
      setOrgId(next);
    },
    [session],
  );
  const value = useMemo(
    () => ({ session, orgId, signIn, signOut, selectOrg }),
    [session, orgId, signIn, signOut, selectOrg],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}

/** Local mock IdP (available only when the API runs in local/test). */
export async function devSignIn(
  email: string,
  name: string,
  identityProvider?: string,
): Promise<Session> {
  const sub = `dev-${email.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const resp = await fetch("/v1/dev/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // local only: "signing in through" an organisation's identity provider (SSO preview)
    body: JSON.stringify({ sub, email, name, identity_provider: identityProvider ?? null }),
  });
  if (!resp.ok) throw new Error(`sign-in failed (${resp.status})`);
  const { access_token: token } = (await resp.json()) as { access_token: string };
  return { token, sub, email, name };
}
