/**
 * Hand-over of what an e-mail link or provider redirect carried in the URL fragment
 * (recovery token, confirmation, error) from the router to the screen that handles it.
 * Memory only: the fragment is removed from the address bar immediately and the recovery
 * token is never written to any storage.
 */
import { type AuthReturn, parseAuthReturn } from "./supabase";

let stash: AuthReturn = { kind: "none" };

export function stashAuthReturn(value: AuthReturn): void {
  stash = value;
}

export function peekAuthReturn(): AuthReturn {
  return stash;
}

/**
 * Reads a fragment-borne return (`#access_token=...&type=recovery`, `#error=...`) from the
 * current URL, removes the fragment from the address bar and stashes it. Returns the
 * screen path to show, or undefined when the URL carries nothing relevant.
 */
export function captureFragmentReturn(): string | undefined {
  const { pathname, search, hash } = window.location;
  if (!hash) return undefined;
  const parsed = parseAuthReturn("", hash);
  if (parsed.kind === "none" || parsed.kind === "code") return undefined;
  window.history.replaceState(null, "", pathname + search);
  stashAuthReturn(parsed);
  if (parsed.kind === "recovery") return "/auth/reset";
  if (parsed.kind === "confirmed") return "/auth/confirmed";
  return "/auth/callback";
}
