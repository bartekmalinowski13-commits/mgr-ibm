import type { components } from "./schema.gen";

export type Project = components["schemas"]["Project"];
export type Design = components["schemas"]["Design"];
export type DesignCreated = components["schemas"]["DesignCreated"];
export type Run = components["schemas"]["Run"];
export type RunIn = components["schemas"]["RunIn"];
export type AuditEntry = components["schemas"]["AuditEntry"];
export type KbDocument = components["schemas"]["KbDocument"];
export type KbDocumentCreated = components["schemas"]["KbDocumentCreated"];
export type KbKind = NonNullable<components["schemas"]["KbDocumentIn"]["kind"]>;
export type Requirements = NonNullable<RunIn["requirements"]>;
export type Variant = NonNullable<RunIn["variant"]>;

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

/* BomVersion JSON (packages/py/bom-core/model.py) - served raw by /v1/runs/{id}/bom */
export type ProvenanceKind = "parser" | "rule" | "agent" | "user";

export interface KbCitation {
  document_id: string;
  chunk_id: string;
  page: number | null;
  scope: "global" | "tenant";
  quote: string;
}

export interface Provenance {
  kind: ProvenanceKind;
  rule_id: string | null;
  rule_pack: string | null;
  rule_pack_version: string | null;
  agent: string | null;
  model_id: string | null;
  prompt_id: string | null;
  prompt_version: string | null;
  citations: KbCitation[];
  rationale: string;
  parser: string | null;
  user_id: string | null;
  at: string;
}

export interface BomItem {
  line: number;
  refdes: string[];
  quantity: number;
  kind: string;
  value: string;
  value_normalized: string | null;
  footprint: string;
  package: string | null;
  manufacturer: string;
  mpn: string;
  description: string;
  dnp: boolean;
  provenance: Record<string, Provenance>;
}

export type Severity = "error" | "warning" | "review" | "info";

export interface Finding {
  rule_id: string;
  severity: Severity;
  message: string;
  refdes: string[];
  field: string | null;
  line: number | null;
  rule_pack: string;
  rule_pack_version: string;
}

export interface Usage {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  cost_eur: number;
  wall_time_s: number;
  tool_calls: number;
}

export interface BomVersion {
  id: string;
  design_name: string;
  variant: string;
  items: BomItem[];
  findings: Finding[];
  usage: Usage;
  rule_pack: string | null;
  rule_pack_version: string | null;
  kb_snapshot_id: string | null;
}

export interface TraceStep {
  step: string;
  kind: "llm" | "rule" | "tool" | "parser";
  agent: string;
  status: "ok" | "error" | "skipped";
  summary: string;
  duration_s: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface RunTrace {
  status: "completed" | "failed";
  error: string | null;
  trace: TraceStep[];
  usage: Usage;
  model: Record<string, string>;
}

export interface Organisation {
  id: string;
  name: string;
  plan: string;
}
