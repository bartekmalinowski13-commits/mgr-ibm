import type { BomItem } from "./provenance";

export type CsvColumn =
  | "line"
  | "refdes"
  | "qty"
  | "value"
  | "footprint"
  | "manufacturer"
  | "mpn"
  | "notes";

function cell(item: BomItem, col: CsvColumn): string {
  switch (col) {
    case "line":
      return String(item.line);
    case "refdes":
      return item.refdes.join(", ");
    case "qty":
      return String(item.quantity);
    case "value":
      return item.value ?? "";
    case "footprint":
      return item.package ?? item.footprint ?? "";
    case "manufacturer":
      return item.manufacturer ?? "";
    case "mpn":
      return item.mpn ?? "";
    case "notes":
      return item.dnp ? "DNP" : "";
  }
}

/** Free-text filter: every whitespace-separated term must appear in some text column. */
export function matchesQuery(item: BomItem, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const hay = [
    item.refdes.join(" "),
    item.value,
    item.footprint,
    item.package,
    item.manufacturer,
    item.mpn,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return terms.every((t) => hay.includes(t));
}

function csvCell(raw: string): string {
  // A leading = + - @ would be run as a formula by spreadsheets (CSV injection).
  const safe = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

export function bomToCsv(items: BomItem[], columns: CsvColumn[]): string {
  const rows = items.map((i) => columns.map((c) => csvCell(cell(i, c))).join(","));
  return [columns.join(","), ...rows].join("\n");
}

/** "C1, C2, C3, C14" -> "C1–C3, C14": runs of three or more consecutive designators collapse. */
export function compressRefdes(refdes: string[]): string {
  const parsed = refdes.map((r) => {
    const m = /^([A-Za-z_#]+)(\d+)$/.exec(r);
    return m
      ? { prefix: m[1] as string, n: Number(m[2]), raw: r }
      : { prefix: r, n: Number.NaN, raw: r };
  });
  const out: string[] = [];
  let i = 0;
  while (i < parsed.length) {
    const start = parsed[i] as (typeof parsed)[number];
    let j = i;
    while (
      j + 1 < parsed.length &&
      !Number.isNaN(start.n) &&
      (parsed[j + 1] as (typeof parsed)[number]).prefix === start.prefix &&
      (parsed[j + 1] as (typeof parsed)[number]).n === (parsed[j] as (typeof parsed)[number]).n + 1
    )
      j += 1;
    if (j - i >= 2) out.push(`${start.raw}–${(parsed[j] as (typeof parsed)[number]).raw}`);
    else for (let k = i; k <= j; k += 1) out.push((parsed[k] as (typeof parsed)[number]).raw);
    i = j + 1;
  }
  return out.join(", ");
}

export type Validation = "ok" | "review" | "error" | "dnp";

/** Worst validation state of a line, from its findings (error > warning/review > ok). */
export function validationOf(
  item: Pick<BomItem, "dnp">,
  findings: { severity: string }[],
): Validation {
  if (findings.some((f) => f.severity === "error")) return "error";
  if (findings.some((f) => f.severity === "warning" || f.severity === "review")) return "review";
  if (item.dnp) return "dnp";
  return "ok";
}

/** Short label of a rule for the validation column ("iec60601.isolation" -> "IEC 60601"). */
export function ruleLabel(ruleId: string): string {
  const head = ruleId.split(".")[0] ?? ruleId;
  const iec = /^iec(\d+)$/i.exec(head);
  return iec ? `IEC ${iec[1]}` : head;
}
