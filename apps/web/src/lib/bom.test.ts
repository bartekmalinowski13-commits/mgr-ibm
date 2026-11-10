import type { BomItem, BomVersion, Finding } from "../api/types";
import { findingsByLine, lineProvenance, toCsv, worstSeverity } from "./bom";

const prov = (kind: "agent" | "rule" | "parser" | "user") => ({
  kind,
  rule_id: null,
  rule_pack: null,
  rule_pack_version: null,
  agent: null,
  model_id: null,
  prompt_id: null,
  prompt_version: null,
  citations: [],
  rationale: "",
  parser: null,
  user_id: null,
  at: "2026-11-10T00:00:00Z",
});

function item(line: number, extra: Partial<BomItem> = {}): BomItem {
  return {
    line,
    refdes: [`R${line}`],
    quantity: 1,
    kind: "resistor",
    value: "10k",
    value_normalized: "10 kΩ",
    footprint: "Resistor_SMD:R_0603_1608Metric",
    package: "0603",
    manufacturer: "Yageo",
    mpn: "RC0603FR-0710KL",
    description: "",
    dnp: false,
    provenance: { item: prov("rule") },
    ...extra,
  };
}

function finding(line: number | null, severity: Finding["severity"]): Finding {
  return {
    rule_id: "x",
    severity,
    message: "m",
    refdes: [],
    field: null,
    line,
    rule_pack: "core",
    rule_pack_version: "1.0.0",
  };
}

function bom(items: BomItem[], findings: Finding[] = []): BomVersion {
  const usage = {
    llm_calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_input_tokens: 0,
    cost_eur: 0,
    wall_time_s: 0,
    tool_calls: 0,
  };
  return {
    id: "b",
    design_name: "d",
    variant: "B",
    items,
    findings,
    usage,
    rule_pack: null,
    rule_pack_version: null,
    kb_snapshot_id: null,
  };
}

describe("lineProvenance", () => {
  it("prefers the MPN decision over the line decision", () => {
    expect(
      lineProvenance(item(1, { provenance: { item: prov("rule"), mpn: prov("agent") } })),
    ).toBe("agent");
    expect(lineProvenance(item(1))).toBe("rule");
    expect(lineProvenance(item(1, { provenance: {} }))).toBe("parser");
  });
});

describe("findings", () => {
  it("groups by line and picks the worst severity", () => {
    const b = bom(
      [item(1), item(2)],
      [finding(1, "info"), finding(1, "warning"), finding(null, "error")],
    );
    const byLine = findingsByLine(b);
    expect(byLine.get(1)).toHaveLength(2);
    expect(byLine.has(2)).toBe(false);
    expect(worstSeverity(byLine.get(1))).toBe("warning");
    expect(worstSeverity(undefined)).toBeNull();
  });
});

describe("toCsv", () => {
  it("neutralises spreadsheet formulas and quotes separators", () => {
    const csv = toCsv(bom([item(1, { mpn: '=HYPERLINK("http://x")', manufacturer: "A, B" })]));
    const row = csv.split("\n")[1] ?? "";
    expect(row).toContain('"\'=HYPERLINK(""http://x"")"');
    expect(row).toContain('"A, B"');
    expect(csv.split("\n")[0]).toMatch(/^Line,Reference,Qty/);
  });
});
