/**
 * Comparison key of a component value, so that notations of the same value compare equal:
 * `100n` = `100 nF`, `4k7` = `4.7 kΩ`, `10M` = `10 MΩ`, `220R@100MHz` = `220 Ω @ 100 MHz`.
 * A lighter counterpart of `bomagent_bom.values.normalize_value` (Python), used only to
 * decide whether two variants disagree; values are never rewritten for display.
 * Every numeric token becomes its plain number (units dropped: both sides describe the
 * same designator, so the unit is implied); anything else compares case-insensitively.
 */

const PREFIX: Record<string, number> = {
  p: -12,
  n: -9,
  u: -6,
  µ: -6,
  μ: -6,
  m: -3,
  k: 3,
  K: 3,
  M: 6,
  G: 9,
};
const UNIT = "(?:Ω|Ω|ohms?|F|H|V|A|W|Hz)";
// "10 kΩ" / "100 nF" / "100 MHz": join a number with its (prefixed) unit
const SPACED = new RegExp(`(\\d)\\s+((?:MEG|[pnuµμmkKMG])?${UNIT}?)(?=$|[\\s@/;,])`, "gi");
// 4k7, 220R, 100n, 2.2 MEG, 10 MΩ: number, optional infix/suffix prefix or R, optional unit
const QUANTITY = new RegExp(`^(\\d*(?:[.,]\\d+)?)(MEG|[pnuµμmkKMGR])?(\\d*)${UNIT}?$`, "i");

function quantity(token: string): string | null {
  const m = QUANTITY.exec(token);
  if (!m) return null;
  const [, head = "", rawPrefix = "", tail = ""] = m;
  if (!head && !tail) return null;
  if (/[.,]/.test(head) && tail) return null; // "4.7k7" is not a value
  // case matters for m (milli) vs M (mega); "MEG" is mega in any case; R is the decimal point
  const prefix = rawPrefix.toUpperCase() === "MEG" ? "M" : rawPrefix;
  const exp = prefix.toUpperCase() === "R" ? 0 : (PREFIX[prefix] ?? 0);
  const number = Number(`${head.replace(",", ".") || "0"}${tail ? `.${tail}` : ""}`);
  if (!Number.isFinite(number)) return null;
  return String(Number((number * 10 ** exp).toPrecision(12)));
}

export function valueKey(value: string | null | undefined): string {
  const text = (value ?? "")
    .trim()
    .replace(/\s*@\s*/g, " @ ")
    .replace(SPACED, "$1$2");
  const tokens = text.split(/[\s@/;]+/).filter(Boolean);
  if (tokens.length === 0) return "";
  const keys = tokens.map(quantity);
  // a part name such as "AD8232" or a free-text label: compare as text
  if (keys[0] === null) return text.toLowerCase().replace(/\s+/g, " ");
  return keys.map((k, i) => k ?? (tokens[i] ?? "").toLowerCase()).join(" ");
}

export const valuesEquivalent = (a: string | null | undefined, b: string | null | undefined) =>
  valueKey(a) === valueKey(b);
