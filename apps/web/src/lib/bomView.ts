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
