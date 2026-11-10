import bomA from "../mocks/data/ecg-A-bom.json";
import resultA from "../mocks/data/ecg-A-result.json";
import bomB from "../mocks/data/ecg-B-bom.json";
import resultB from "../mocks/data/ecg-B-result.json";
import { type Api, ApiError, kbMimeType } from "./client";
import type {
  AuditEntry,
  BomVersion,
  Design,
  DesignCreated,
  KbDocument,
  KbKind,
  Organisation,
  Page,
  Project,
  Run,
  RunIn,
  RunTrace,
} from "./types";

/** In-memory backend for design review and E2E tests. Data: the ECG fixture run through
 * variants A and B with the simulated model (`bomagent run`) - plumbing, not research data. */

const ORGS: Organisation[] = [
  { id: "org-medtech", name: "Pomorskie Laboratorium Medtech", plan: "pilot" },
  { id: "org-research", name: "Zespół badawczy IBM", plan: "team" },
];

const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();

interface OrgState {
  projects: Project[];
  designs: Design[];
  runs: Run[];
  boms: Record<string, BomVersion>;
  traces: Record<string, RunTrace>;
  audit: AuditEntry[];
  kb: KbDocument[];
}

function seed(): OrgState {
  const projectId = uid();
  const designId = uid();
  const t0 = new Date(Date.now() - 1000 * 60 * 42).toISOString();
  const runA = uid();
  const runB = uid();
  const run = (id: string, variant: string, trace: RunTrace): Run => ({
    id,
    design_id: designId,
    variant,
    model_id: "fake-closed",
    status: "completed",
    usage: trace.usage as unknown as Run["usage"],
    created_by: "bartek",
    created_at: t0,
    started_at: t0,
    finished_at: t0,
    error: null,
  });
  const state: OrgState = {
    projects: [
      { id: projectId, name: "Monitor EKG, 1 odprowadzenie", created_by: "bartek", created_at: t0 },
    ],
    designs: [
      {
        id: designId,
        project_id: projectId,
        status: "parsed",
        filenames: ["ecg-frontend.kicad_sch", "afe.kicad_sch", "power.kicad_sch"],
        source_format: "kicad8",
        components: 30,
        confidence: 1,
        limitations: [],
        error: null,
        created_at: t0,
      },
    ],
    runs: [
      run(runB, "B", resultB as unknown as RunTrace),
      run(runA, "A", resultA as unknown as RunTrace),
    ],
    boms: { [runA]: bomA as unknown as BomVersion, [runB]: bomB as unknown as BomVersion },
    traces: { [runA]: resultA as unknown as RunTrace, [runB]: resultB as unknown as RunTrace },
    audit: [],
    kb: [
      kbDoc("AD8232 – karta katalogowa", "datasheet", "Analog Devices", "tenant", t0),
      kbDoc("Wytyczne doboru złączy elektrod", "application_note", "", "tenant", t0),
      ...GLOBAL_KB(t0),
    ],
  };
  let seq = 0;
  for (const [action, type, id, actor] of [
    ["project.create", "project", projectId, "bartek"],
    ["design.create", "design", designId, "bartek"],
    ["design.upload_complete", "design", designId, "bartek"],
    ["design.parse", "design", designId, "ingest-worker"],
    ["run.create", "run", runA, "bartek"],
    ["run.completed", "run", runA, "agent-worker"],
    ["run.create", "run", runB, "bartek"],
    ["run.completed", "run", runB, "agent-worker"],
  ] as const) {
    seq += 1;
    state.audit.unshift({
      seq,
      occurred_at: t0,
      actor_type: actor.endsWith("worker") ? "service" : "user",
      actor_id: actor,
      action,
      object_type: type,
      object_id: id,
      hash: (seq * 2654435761).toString(16).padStart(16, "0").repeat(4).slice(0, 64),
    });
  }
  return state;
}

export class MockApi implements Api {
  readonly mode = "mock" as const;
  private orgs: Record<string, OrgState> = { "org-medtech": seed(), "org-research": emptyState() };
  constructor(private activeOrg: () => string = () => "org-medtech") {}

  private get s(): OrgState {
    const org = this.orgs[this.activeOrg()];
    if (!org) throw new ApiError(404, "Not Found");
    return org;
  }
  private audit(action: string, object_type: string, object_id: string, actor = "bartek") {
    const seq = (this.s.audit[0]?.seq ?? 0) + 1;
    this.s.audit.unshift({
      seq,
      occurred_at: now(),
      actor_type: actor.endsWith("worker") ? "service" : "user",
      actor_id: actor,
      action,
      object_type,
      object_id,
      hash: (seq * 2654435761).toString(16).padStart(16, "0").repeat(4).slice(0, 64),
    });
  }

  async organisations() {
    return ORGS;
  }
  async listProjects() {
    return { items: [...this.s.projects] };
  }
  async createProject(name: string) {
    const p: Project = { id: uid(), name, created_by: "bartek", created_at: now() };
    this.s.projects.unshift(p);
    this.audit("project.create", "project", p.id);
    return p;
  }
  async listDesigns(projectId: string): Promise<Page<Design>> {
    return { items: this.s.designs.filter((d) => d.project_id === projectId) };
  }
  async createDesign(projectId: string, files: File[]): Promise<DesignCreated> {
    const brd = files.some((f) => f.name.endsWith(".brd"));
    const d: Design = {
      id: uid(),
      project_id: projectId,
      status: "uploaded",
      filenames: files.map((f) => f.name),
      limitations: [],
      created_at: now(),
      error: null,
    };
    this.s.designs.unshift(d);
    this.audit("design.create", "design", d.id);
    setTimeout(() => {
      if (brd) {
        Object.assign(d, {
          status: "failed",
          error:
            "Plik .brd nie jest obsługiwany bezpośrednio. Wyeksportuj IPC-2581 z Allegro i wgraj go tutaj.",
        });
      } else {
        Object.assign(d, {
          status: "parsed",
          source_format: "kicad8",
          components: 30,
          confidence: 1,
        });
        this.audit("design.parse", "design", d.id, "ingest-worker");
      }
    }, 800);
    return {
      ...d,
      uploads: files.map((f) => ({ filename: f.name, url: "mock://", method: "PUT" as const })),
    };
  }
  async getDesign(designId: string) {
    const d = this.s.designs.find((x) => x.id === designId);
    if (!d) throw new ApiError(404, "Not Found", "design not found");
    return d;
  }
  async listRuns() {
    return { items: [...this.s.runs] };
  }
  async getRun(runId: string) {
    const r = this.s.runs.find((x) => x.id === runId);
    if (!r) throw new ApiError(404, "Not Found", "run not found");
    return { ...r };
  }
  async createRun(body: RunIn, _key: string) {
    const design = await this.getDesign(body.design_id);
    if (design.status !== "parsed") throw new ApiError(409, "Conflict", "design is not parsed");
    const variant = body.variant ?? "B";
    const source = variant === "A" ? resultA : resultB;
    const r: Run = {
      id: uid(),
      design_id: body.design_id,
      variant,
      model_id: body.model_id,
      status: "queued",
      created_by: "bartek",
      created_at: now(),
      usage: null,
      error: null,
    };
    this.s.runs.unshift(r);
    this.s.boms[r.id] = (variant === "A" ? bomA : bomB) as unknown as BomVersion;
    const liveTrace: RunTrace = { ...(source as unknown as RunTrace), trace: [] };
    this.s.traces[r.id] = liveTrace;
    this.audit("run.create", "run", r.id);
    const steps = (source as unknown as RunTrace).trace;
    steps.forEach((step, i) => {
      setTimeout(
        () => {
          r.status = "running";
          r.started_at ??= now();
          liveTrace.trace.push(step);
          if (i === steps.length - 1) {
            r.status = "completed";
            r.finished_at = now();
            r.usage = (source as unknown as RunTrace).usage as unknown as Run["usage"];
            this.audit("run.completed", "run", r.id, "agent-worker");
          }
        },
        500 + i * 650,
      );
    });
    return { ...r };
  }
  async getBom(runId: string) {
    const run = await this.getRun(runId);
    if (run.status !== "completed") throw new ApiError(409, "Conflict", "BOM is not available yet");
    const bom = this.s.boms[runId];
    if (!bom) throw new ApiError(404, "Not Found");
    return bom;
  }
  async getTrace(runId: string) {
    const t = this.s.traces[runId];
    if (!t) throw new ApiError(404, "Not Found");
    return { ...t, trace: [...t.trace] };
  }
  watchRun(runId: string, onUpdate: (run: Run) => void) {
    let last = "";
    const timer = setInterval(async () => {
      const run = await this.getRun(runId).catch(() => null);
      if (!run) return;
      const sig = `${run.status}:${this.s.traces[runId]?.trace.length ?? 0}`;
      if (sig !== last) {
        last = sig;
        onUpdate(run);
      }
      if (run.status === "completed" || run.status === "failed") clearInterval(timer);
    }, 250);
    return () => clearInterval(timer);
  }
  async auditEvents() {
    return { items: [...this.s.audit] };
  }
  async listKbDocuments() {
    return { items: [...this.s.kb] };
  }
  async uploadKbDocument(file: File, meta: { title: string; kind: KbKind; manufacturer: string }) {
    if (!kbMimeType(file.name)) throw new ApiError(422, "Unsupported file type");
    const doc: KbDocument = {
      ...kbDoc(meta.title, meta.kind, meta.manufacturer, "tenant", now()),
      mime_type: kbMimeType(file.name) ?? "application/pdf",
      size_bytes: file.size,
      status: "indexing",
      indexed_at: null,
    };
    this.s.kb.unshift(doc);
    this.audit("kb.document.created", "kb_document", doc.id);
    setTimeout(() => {
      Object.assign(doc, { status: "indexed", indexed_at: now() });
    }, 900);
    return { ...doc };
  }
}

function emptyState(): OrgState {
  return {
    projects: [],
    designs: [],
    runs: [],
    boms: {},
    traces: {},
    audit: [],
    kb: GLOBAL_KB(now()),
  };
}

function kbDoc(
  title: string,
  kind: KbDocument["kind"],
  manufacturer: string,
  scope: KbDocument["scope"],
  at: string,
): KbDocument {
  return {
    id: uid(),
    scope,
    title,
    kind,
    manufacturer,
    mime_type: "application/pdf",
    sha256: "0".repeat(64),
    size_bytes: 240_000 + title.length * 1000,
    status: "indexed",
    created_by: scope === "global" ? "platform" : "bartek",
    created_at: at,
    indexed_at: at,
    error: null,
  };
}

/* The shared corpus every organisation can read (read-only for tenants). */
const GLOBAL_KB = (at: string) => [
  kbDoc("IEC 60601-1 – streszczenie wymagań dla BOM", "standard", "", "global", at),
  kbDoc("Kondensatory MLCC – noty doboru", "application_note", "Murata", "global", at),
];
