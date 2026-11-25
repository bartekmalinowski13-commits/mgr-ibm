import { describe, expect, it } from "vitest";
import { bomToCsv, compressRefdes, matchesQuery, ruleLabel, validationOf } from "./bomView";
import type { BomItem } from "./provenance";

const it1 = {
  line: 1,
  refdes: ["C1", "C2"],
  quantity: 2,
  value: "100nF",
  footprint: "Cap:C_0603",
  manufacturer: "Murata",
  mpn: "GRM188",
  dnp: false,
} as unknown as BomItem;
const it2 = { ...it1, line: 2, refdes: ["R1"], value: '10k, "1%"', mpn: "", dnp: true } as BomItem;

describe("matchesQuery", () => {
  it("matches any text column case-insensitively and ignores blanks", () => {
    expect(matchesQuery(it1, "")).toBe(true);
    expect(matchesQuery(it1, "  ")).toBe(true);
    expect(matchesQuery(it1, "grm")).toBe(true);
    expect(matchesQuery(it1, "c2")).toBe(true);
    expect(matchesQuery(it1, "murata 100")).toBe(true);
    expect(matchesQuery(it1, "tdk")).toBe(false);
  });
});

describe("bomToCsv", () => {
  it("writes a header, escapes quotes and commas, and honours the column list", () => {
    const csv = bomToCsv([it1, it2], ["line", "refdes", "value", "mpn"]);
    const lines = csv.split("\n");
    expect(lines[0]).toBe("line,refdes,value,mpn");
    expect(lines[1]).toBe('1,"C1, C2",100nF,GRM188');
    expect(lines[2]).toBe('2,R1,"10k, ""1%""",');
  });
  it("neutralises spreadsheet formulas", () => {
    const evil = { ...it1, value: "=HYPERLINK(1)" } as BomItem;
    expect(bomToCsv([evil], ["value"]).split("\n")[1]).toBe("'=HYPERLINK(1)");
  });
});

describe("compressRefdes", () => {
  it("collapses runs of three or more", () => {
    expect(compressRefdes(["C1", "C2", "C3", "C4", "C14"])).toBe("C1–C4, C14");
    expect(compressRefdes(["C10", "C11"])).toBe("C10, C11");
    expect(compressRefdes(["R1", "R2", "R3", "U1", "U2"])).toBe("R1–R3, U1, U2");
    expect(compressRefdes(["J1"])).toBe("J1");
  });
});

describe("validationOf / ruleLabel", () => {
  it("picks the worst finding", () => {
    expect(validationOf({ dnp: false }, [])).toBe("ok");
    expect(validationOf({ dnp: true }, [])).toBe("dnp");
    expect(validationOf({ dnp: false }, [{ severity: "review" }])).toBe("review");
    expect(validationOf({ dnp: false }, [{ severity: "review" }, { severity: "error" }])).toBe(
      "error",
    );
  });
  it("shortens rule ids", () => {
    expect(ruleLabel("iec60601.isolation")).toBe("IEC 60601");
    expect(ruleLabel("mpn.dielectric")).toBe("mpn");
  });
});
