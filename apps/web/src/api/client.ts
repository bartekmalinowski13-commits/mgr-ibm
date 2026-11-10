import { readStored } from "../lib/storage";
import type {
  AuditEntry,
  BomVersion,
  Design,
  DesignCreated,
  KbDocument,
  KbDocumentCreated,
  KbKind,
  Organisation,
  Page,
  Project,
  Run,
  RunIn,
  RunTrace,
} from "./types";

/** Everything the UI needs from the backend. Two implementations: HTTP (API v1) and an
 * in-memory mock for design review and E2E tests without a backend. */
export interface Api {
  readonly mode: "http" | "mock";
  organisations(): Promise<Organisation[]>;
  listProjects(): Promise<Page<Project>>;
  createProject(name: string): Promise<Project>;
  listDesigns(projectId: string): Promise<Page<Design>>;
  createDesign(projectId: string, files: File[]): Promise<DesignCreated>;
  getDesign(designId: string): Promise<Design>;
  listRuns(): Promise<Page<Run>>;
  getRun(runId: string): Promise<Run>;
  createRun(body: RunIn, idempotencyKey: string): Promise<Run>;
  getBom(runId: string): Promise<BomVersion>;
  getTrace(runId: string): Promise<RunTrace>;
  watchRun(runId: string, onUpdate: (run: Run) => void): () => void;
  auditEvents(): Promise<Page<AuditEntry>>;
  listKbDocuments(): Promise<Page<KbDocument>>;
  uploadKbDocument(
    file: File,
    meta: { title: string; kind: KbKind; manufacturer: string },
  ): Promise<KbDocument>;
}

export const KB_MIME: Record<
  string,
  "application/pdf" | "text/markdown" | "text/plain" | "text/html"
> = {
  pdf: "application/pdf",
  md: "text/markdown",
  txt: "text/plain",
  html: "text/html",
};

export function kbMimeType(filename: string) {
  return KB_MIME[filename.split(".").pop()?.toLowerCase() ?? ""];
}

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    readonly detail?: string,
  ) {
    super(detail ?? title);
  }
}

function token(): string {
  return readStored("bomagent_token") ?? import.meta.env.VITE_DEV_TOKEN ?? "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token()}`,
      ...(init.body && !(init.body instanceof Blob) ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    let problem: { title?: string; detail?: string } = {};
    try {
      problem = await res.json();
    } catch {
      /* not problem+json */
    }
    throw new ApiError(res.status, problem.title ?? res.statusText, problem.detail);
  }
  return (await res.json()) as T;
}

export class HttpApi implements Api {
  readonly mode = "http" as const;

  async organisations(): Promise<Organisation[]> {
    // the active organisation comes from the token; switching = signing in to another org
    return [{ id: "current", name: "Organizacja", plan: "pilot" }];
  }
  listProjects() {
    return request<Page<Project>>("/v1/projects?limit=50");
  }
  createProject(name: string) {
    return request<Project>("/v1/projects", { method: "POST", body: JSON.stringify({ name }) });
  }
  listDesigns(projectId: string) {
    return request<Page<Design>>(`/v1/projects/${projectId}/designs?limit=50`);
  }
  async createDesign(projectId: string, files: File[]) {
    const created = await request<DesignCreated>(`/v1/projects/${projectId}/designs`, {
      method: "POST",
      body: JSON.stringify({ filenames: files.map((f) => f.name) }),
    });
    await Promise.all(
      created.uploads.map((u) => {
        const file = files.find((f) => f.name === u.filename);
        return fetch(u.url, { method: "PUT", body: file });
      }),
    );
    await request<Design>(`/v1/designs/${created.id}/complete`, { method: "POST" });
    return created;
  }
  getDesign(designId: string) {
    return request<Design>(`/v1/designs/${designId}`);
  }
  listRuns() {
    return request<Page<Run>>("/v1/runs?limit=50");
  }
  getRun(runId: string) {
    return request<Run>(`/v1/runs/${runId}`);
  }
  createRun(body: RunIn, idempotencyKey: string) {
    return request<Run>("/v1/runs", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }
  getBom(runId: string) {
    return request<BomVersion>(`/v1/runs/${runId}/bom`);
  }
  getTrace(runId: string) {
    return request<RunTrace>(`/v1/runs/${runId}/trace`);
  }
  watchRun(runId: string, onUpdate: (run: Run) => void) {
    // EventSource cannot send headers; fetch-based reader keeps the bearer token
    const ctrl = new AbortController();
    (async () => {
      const res = await fetch(`/v1/runs/${runId}/events`, {
        headers: { Authorization: `Bearer ${token()}` },
        signal: ctrl.signal,
      });
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        for (const block of buffer.split("\n\n").slice(0, -1)) {
          const data = block.split("\n").find((l) => l.startsWith("data: "));
          if (data) onUpdate(JSON.parse(data.slice(6)) as Run);
        }
        buffer = buffer.slice(buffer.lastIndexOf("\n\n") + 2);
      }
    })().catch(() => undefined);
    return () => ctrl.abort();
  }
  auditEvents() {
    return request<Page<AuditEntry>>("/v1/audit/events?limit=100");
  }
  listKbDocuments() {
    return request<Page<KbDocument>>("/v1/kb/documents?limit=100");
  }
  async uploadKbDocument(file: File, meta: { title: string; kind: KbKind; manufacturer: string }) {
    const mime = kbMimeType(file.name);
    if (!mime) throw new ApiError(422, "Unsupported file type");
    const created = await request<KbDocumentCreated>("/v1/kb/documents", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        title: meta.title,
        kind: meta.kind,
        manufacturer: meta.manufacturer,
        mime_type: mime,
        sha256: await sha256Hex(file),
        size_bytes: file.size,
      }),
    });
    if (!created.upload) return created; // same file already in the knowledge base
    await fetch(created.upload.url, { method: "PUT", body: file });
    return request<KbDocument>(`/v1/kb/documents/${created.id}/complete`, { method: "POST" });
  }
}
