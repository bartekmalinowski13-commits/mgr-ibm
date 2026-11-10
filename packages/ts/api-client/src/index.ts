/**
 * Typed client for the BOM Agent /v1 API.
 *
 * Types are generated from the committed OpenAPI 3.1 contract (`pnpm run generate`), so a
 * breaking API change fails `tsc` in the web app instead of at runtime.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema.gen";

export type { components, paths };
export type Project = components["schemas"]["Project"];
export type Run = components["schemas"]["Run"];
export type BomEnvelope = components["schemas"]["BomEnvelope"];
export type Problem = components["schemas"]["Problem"];

export interface ClientOptions {
  baseUrl: string;
  /** Returns the current OIDC access token (refreshing it when needed). */
  getToken: () => string | Promise<string>;
  /** Active organisation (X-Org-Id); omit for /v1/me and onboarding. */
  getOrgId?: () => string | undefined;
  fetch?: typeof fetch;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
  }
}

export function createApiClient(options: ClientOptions) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    fetch: options.fetch,
  });
  const auth: Middleware = {
    async onRequest({ request }) {
      request.headers.set("Authorization", `Bearer ${await options.getToken()}`);
      const org = options.getOrgId?.();
      if (org) request.headers.set("X-Org-Id", org);
      return request;
    },
  };
  client.use(auth);
  return client;
}

/** Unwraps an openapi-fetch result: returns data or throws ApiError with the RFC 9457 body. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined && result.response.ok) return result.data;
  throw new ApiError(result.response.status, result.error as Problem);
}

/** A fresh idempotency key for creating POSTs (retry-safe). */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}
