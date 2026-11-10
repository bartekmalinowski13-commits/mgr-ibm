import type { BomItem, BomVersion, Finding, ProvenanceKind, Severity } from "../api/types";

const SEVERITY_RANK: Record<Severity, number> = { error: 3, warning: 2, review: 1, info: 0 };

/** Who decided the line: the MPN decision if there is one (the most consequential field),
 * otherwise the line-level decision. */
export function lineProvenance(item: BomItem): ProvenanceKind {
  return (item.provenance.mpn ?? item.provenance.item)?.kind ?? "parser";
}

export function findingsByLine(bom: BomVersion): Map<number, Finding[]> {
  const out = new Map<number, Finding[]>();
  for (const f of bom.findings) {
    if (f.line == null) continue;
    out.set(f.line, [...(out.get(f.line) ?? []), f]);
  }
  return out;
}

export function worstSeverity(findings: Finding[] | undefined): Severity | null {
  if (!findings?.length) return null;
  return findings.reduce<Severity>(
    (worst, f) => (SEVERITY_RANK[f.severity] > SEVERITY_RANK[worst] ? f.severity : worst),
    "info",
  );
}

function csvCell(value: string | number | boolean): string {
  const s = String(value);
  // neutralise spreadsheet formulas (CSV injection) and quote when needed
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n;]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

export function toCsv(bom: BomVersion): string {
  const header = [
    "Line",
    "Reference",
    "Qty",
    "Value",
    "Footprint",
    "Manufacturer",
    "MPN",
    "DNP",
    "Decided by",
  ];
  const rows = bom.items.map((i) => [
    i.line,
    i.refdes.join(" "),
    i.quantity,
    i.value_normalized ?? i.value,
    i.footprint,
    i.manufacturer,
    i.mpn,
    i.dnp,
    lineProvenance(i),
  ]);
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\n");
}

export function shortFootprint(fp: string): string {
  return fp.includes(":") ? (fp.split(":")[1] ?? fp) : fp;
}
