import { idempotencyKey } from "@bomagent/api-client";
import { useRef } from "react";

/**
 * Idempotency keys per user intent. A retry or double submit of the same form reuses the key,
 * so the API replays the first result instead of creating a second project or run; a changed
 * form, or a new submit after success, gets a new key.
 */
export class IntentKeys {
  private readonly entries = new Map<string, { payload: string; key: string }>();

  /** The key for `scope` (e.g. one per run variant) and this exact payload. */
  keyFor(scope: string, payload: unknown): string {
    const serialised = JSON.stringify(payload) ?? "";
    const entry = this.entries.get(scope);
    if (entry && entry.payload === serialised) return entry.key;
    const key = idempotencyKey();
    this.entries.set(scope, { payload: serialised, key });
    return key;
  }

  /** The intent succeeded: the next submit of `scope` (or of every scope) is a new intent. */
  done(scope?: string): void {
    if (scope === undefined) this.entries.clear();
    else this.entries.delete(scope);
  }
}

/** IntentKeys that live as long as the component (the dialog or form). */
export function useIntentKeys(): IntentKeys {
  const ref = useRef<IntentKeys>(null);
  if (!ref.current) ref.current = new IntentKeys();
  return ref.current;
}
