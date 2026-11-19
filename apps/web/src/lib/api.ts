import { ApiError, type components, createApiClient, toProblem } from "@bomagent/api-client";
import i18n from "./i18n";
import { auth } from "./session";

export type Schemas = components["schemas"];
export { ApiError };

export const api = createApiClient({
  baseUrl: typeof window === "undefined" ? "http://localhost" : window.location.origin,
  getToken: () => auth.token,
  getOrgId: () => auth.orgId,
});

/** Data of a successful call, ApiError (RFC 9457) otherwise; 204 resolves to undefined. */
export async function call<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const result = await promise;
  if (result.response.ok) return result.data as T;
  const { status, statusText } = result.response;
  throw new ApiError(status, toProblem(status, statusText, result.error));
}

/**
 * The ApiError for a failed raw `fetch` response. The body is parsed only when it is JSON:
 * a gateway's HTML page (502/504, or a 413 for a large upload) must not surface as a
 * `SyntaxError` from `resp.json()`.
 */
async function failure(resp: Response): Promise<ApiError> {
  let body: unknown;
  if (/^application\/(problem\+)?json/i.test(resp.headers.get("content-type") ?? "")) {
    body = await resp.json().catch(() => undefined);
  }
  return new ApiError(resp.status, toProblem(resp.status, resp.statusText, body));
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { Authorization: `Bearer ${auth.token}` };
  if (auth.orgId) h["X-Org-Id"] = auth.orgId;
  return h;
}

/** Multipart upload (openapi-fetch serialises JSON bodies only). */
export async function uploadFile(projectId: string, file: File): Promise<Schemas["FileInfo"]> {
  const body = new FormData();
  body.append("file", file, file.name);
  const resp = await fetch(`/v1/projects/${projectId}/files`, {
    method: "POST",
    headers: headers(),
    body,
  });
  if (!resp.ok) throw await failure(resp);
  return (await resp.json()) as Schemas["FileInfo"];
}

export async function uploadKbDocument(
  file: File,
  kind: string,
  manufacturer: string,
): Promise<Schemas["KbDocument"]> {
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("kind", kind);
  body.append("manufacturer", manufacturer);
  const resp = await fetch("/v1/kb/documents", { method: "POST", headers: headers(), body });
  if (!resp.ok) throw await failure(resp);
  return (await resp.json()) as Schemas["KbDocument"];
}

export async function evaluateRun(runId: string, file: File): Promise<Schemas["Evaluation"]> {
  const body = new FormData();
  body.append("reference", file, file.name);
  const resp = await fetch(`/v1/runs/${runId}/evaluation`, {
    method: "POST",
    headers: headers(),
    body,
  });
  if (!resp.ok) throw await failure(resp);
  return (await resp.json()) as Schemas["Evaluation"];
}

export async function downloadCsv(runId: string): Promise<Blob> {
  const resp = await fetch(`/v1/runs/${runId}/bom.csv`, { headers: headers() });
  if (!resp.ok) throw await failure(resp);
  return resp.blob();
}

export async function downloadXlsx(runId: string): Promise<Blob> {
  const resp = await fetch(`/v1/runs/${runId}/bom.xlsx`, { headers: headers() });
  if (!resp.ok) throw await failure(resp);
  return resp.blob();
}

/** Save a blob under a file name (object URL + temporary link). */
export function saveBlob(blob: Blob, name: string): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}

export interface RunProgress {
  status: string;
  usage: Record<string, number>;
  steps: number;
  /** last finished step (node name), while the run is running */
  step?: string | null;
}

/**
 * Server-Sent Events over fetch (EventSource cannot send the Authorization header).
 * Calls ``onProgress`` for each ``progress`` event; resolves with the final status.
 */
export async function streamRun(
  runId: string,
  onProgress: (p: RunProgress) => void,
  signal: AbortSignal,
): Promise<string | undefined> {
  const resp = await fetch(`/v1/runs/${runId}/events`, { headers: headers(), signal });
  if (!resp.ok || !resp.body) return undefined;
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let final: string | undefined;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.+)$/m.exec(chunk)?.[1];
      const data = /^data: (.+)$/m.exec(chunk)?.[1];
      if (data && event === "progress") onProgress(JSON.parse(data) as RunProgress);
      if (data && event === "end") final = (JSON.parse(data) as { status: string }).status;
      cut = buffer.indexOf("\n\n");
    }
  }
  return final;
}

/** A localised message for an HTTP status when the body says nothing more useful. */
function statusMessage(status: number): string {
  if (status === 413 || status === 429) return i18n.t(`httpErrors.${status}`);
  if (status >= 500) return i18n.t("httpErrors.5xx");
  return i18n.t("httpErrors.generic", { status });
}

export function problemMessage(error: unknown): string {
  if (error instanceof ApiError) {
    // Localised by problem slug (the last segment of `type`); the server detail is the
    // fallback, and a localised message for the status when there is no detail either.
    const problem: Partial<Schemas["Problem"]> | undefined = error.problem;
    const slug = typeof problem?.type === "string" ? problem.type.split("/problems/")[1] : "";
    const key = `errors.${slug}`;
    if (slug && i18n.exists(key)) return i18n.t(key);
    return problem?.detail || statusMessage(error.status);
  }
  return error instanceof Error ? error.message : String(error);
}
