import { describe, expect, it } from "vitest";
import { findingsFor } from "../screens/BomTable";
import { slugify } from "./format";
import { type BomItem, formatEur, lineProvenance } from "./provenance";

const item = (kinds: string[], extra: Partial<BomItem> = {}): BomItem =>
  ({
    line: 3,
    refdes: ["C4", "C5"],
    quantity: 2,
    provenance: Object.fromEntries(kinds.map((k, i) => [`f${i}`, { kind: k }])),
    ...extra,
  }) as unknown as BomItem;

describe("lineProvenance", () => {
  it("ranks a person over an agent over a rule over the parser", () => {
    expect(lineProvenance(item(["parser"]))).toBe("parser");
    expect(lineProvenance(item(["parser", "rule"]))).toBe("rule");
    expect(lineProvenance(item(["rule", "agent"]))).toBe("agent");
    expect(lineProvenance(item(["agent", "user", "rule"]))).toBe("user");
    expect(lineProvenance(item([]))).toBe("parser");
  });
});

describe("findingsFor", () => {
  it("matches findings by line or by any designator", () => {
    const findings = [
      { rule_id: "a", line: 3, message: "", severity: "warning" },
      { rule_id: "b", refdes: ["C5"], message: "", severity: "review" },
      { rule_id: "c", refdes: ["R1"], message: "", severity: "error" },
    ] as never;
    expect(findingsFor(item(["rule"]), findings).map((f) => f.rule_id)).toEqual(["a", "b"]);
  });
});

describe("slugify", () => {
  it("turns an organisation name into an address", () => {
    expect(slugify("MedTech Kraków")).toBe("medtech-krakow");
    expect(slugify("  Łódź Bio–Devices  ")).toBe("lodz-bio-devices");
  });
});

describe("formatEur", () => {
  it("keeps sub-cent precision for small LLM costs", () => {
    expect(formatEur(0.0042, "en-GB")).toBe("€0.0042");
    expect(formatEur(12.5, "en-GB")).toBe("€12.50");
  });
});
