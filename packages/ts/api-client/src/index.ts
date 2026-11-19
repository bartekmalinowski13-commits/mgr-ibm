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

/**
 * Any error body as an RFC 9457 problem. Proxies and gateways answer with HTML pages, empty
 * bodies or plain JSON (a 502/504, or a 413 at the edge), so only an object with a string
 * `type` and `title` is taken as it is; anything else becomes an `about:blank` problem for
 * the HTTP status.
 */
export function toProblem(status: number, statusText: string, body: unknown): Problem {
  if (
    body &&
    typeof body === "object" &&
    typeof (body as Problem).type === "string" &&
    typeof (body as Problem).title === "string"
  ) {
    return { ...(body as Problem), status: (body as Problem).status ?? status };
  }
  return { type: "about:blank", title: statusText || `HTTP ${status}`, status };
}

export class ApiError extends Error {
  readonly problem: Problem;
  constructor(
    readonly status: number,
    problem: unknown,
  ) {
    const normalised = toProblem(status, "", problem);
    super(normalised.detail ?? normalised.title);
    this.problem = normalised;
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
  const { status, statusText } = result.response;
  throw new ApiError(status, toProblem(status, statusText, result.error));
}

/** A fresh idempotency key for creating POSTs (retry-safe). */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}
