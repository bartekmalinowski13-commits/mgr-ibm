import type { Schemas } from "./api";

export type BomItem = Schemas["BomItem"];
export type ProvenanceKind = "agent" | "rule" | "parser" | "user";

/** Who decided the line: a person beats an agent beats a rule beats the parser. */
export function lineProvenance(item: Pick<BomItem, "provenance">): ProvenanceKind {
  const kinds = new Set(Object.values(item.provenance ?? {}).map((p) => p.kind));
  if (kinds.has("user")) return "user";
  if (kinds.has("agent")) return "agent";
  if (kinds.has("rule")) return "rule";
  return "parser";
}

export const PROVENANCE_COLOR: Record<ProvenanceKind, string> = {
  agent: "bg-llm",
  rule: "bg-rule",
  parser: "bg-parser",
  user: "bg-user",
};

export function formatEur(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}
