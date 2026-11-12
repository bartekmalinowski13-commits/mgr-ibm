import { ApiError, type components, createApiClient, type Problem } from "@bomagent/api-client";
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
  const problem = (result.error ?? {
    title: result.response.statusText,
    status: result.response.status,
  }) as Problem;
  throw new ApiError(result.response.status, problem);
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
  const json = await resp.json();
  if (!resp.ok) throw new ApiError(resp.status, json as Problem);
  return json as Schemas["FileInfo"];
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
  const json = await resp.json();
  if (!resp.ok) throw new ApiError(resp.status, json as Problem);
  return json as Schemas["KbDocument"];
}

export async function evaluateRun(runId: string, file: File): Promise<Schemas["Evaluation"]> {
  const body = new FormData();
  body.append("reference", file, file.name);
  const resp = await fetch(`/v1/runs/${runId}/evaluation`, {
    method: "POST",
    headers: headers(),
    body,
  });
  const json = await resp.json();
  if (!resp.ok) throw new ApiError(resp.status, json as Problem);
  return json as Schemas["Evaluation"];
}

export async function downloadCsv(runId: string): Promise<Blob> {
  const resp = await fetch(`/v1/runs/${runId}/bom.csv`, { headers: headers() });
  if (!resp.ok) throw new ApiError(resp.status, (await resp.json()) as Problem);
  return resp.blob();
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

export function problemMessage(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail ?? error.problem.title;
  return error instanceof Error ? error.message : String(error);
}
