import { describe, expect, it } from "vitest";
import { valueKey, valuesEquivalent } from "./values";

describe("valuesEquivalent", () => {
  it.each([
    ["100n", "100 nF"],
    ["100nF", "0.1uF"],
    ["4k7", "4.7 kΩ"],
    ["4K7", "4.7k"],
    ["10M", "10 MΩ"],
    ["2.2 MEG", "2.2 MΩ"],
    ["1u", "1 µF"],
    ["4u7", "4.7 µF"],
    ["1R0", "1 Ω"],
    ["0R", "0 Ω"],
    ["10 kΩ", "10kohm"],
    ["220R@100MHz", "220 Ω @ 100 MHz"],
    ["0,1µF", "100 nF"],
    ["AD8232", "ad8232"],
    ["Electrodes RA/LA/RL", "electrodes ra/la/rl"],
    ["", ""],
  ])("%s == %s", (a, b) => {
    expect(valuesEquivalent(a, b)).toBe(true);
  });

  it.each([
    ["100n", "10n"],
    ["4k7", "47k"],
    ["1m", "1M"],
    ["220R@100MHz", "600R@100MHz"],
    ["220R@100MHz", "220R@1GHz"],
    ["AD8232", "AD8233"],
    ["10k", ""],
  ])("%s != %s", (a, b) => {
    expect(valuesEquivalent(a, b)).toBe(false);
  });

  it("keeps part names and labels as text", () => {
    expect(valueKey("MCP1700-3.3")).toBe("mcp1700-3.3");
    expect(valueKey("green")).toBe("green");
  });
});
