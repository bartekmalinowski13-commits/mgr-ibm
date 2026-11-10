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

describe("diffBoms", () => {
  it("lists designators whose value, manufacturer or MPN differ, or that one variant lacks", async () => {
    const { diffBoms } = await import("../screens/CompareScreen");
    const line = (refdes: string[], mpn: string) => ({
      line: 1,
      refdes,
      quantity: refdes.length,
      value: "10k",
      manufacturer: "Yageo",
      mpn,
      provenance: {},
    });
    const a = { items: [line(["R1", "R2"], "RC0603FR-0710KL"), line(["C1"], "X")] } as never;
    const b = { items: [line(["R1"], "RC0603FR-0710KL"), line(["R2"], "ERJ-3EKF1002V")] } as never;
    const diffs = diffBoms(a, b);
    expect(diffs.map((d) => [d.refdes, d.changed])).toEqual([
      ["C1", ["value", "manufacturer", "mpn"]],
      ["R1", []],
      ["R2", ["mpn"]],
    ]);
  });
});
