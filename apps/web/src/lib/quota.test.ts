import { describe, expect, it } from "vitest";
import { quotaChips, quotaLevel } from "./quota";

describe("quotaLevel", () => {
  it("is ok below 80 %, warn from 80 %, full from 100 %, ok without a limit", () => {
    expect(quotaLevel(79, 100)).toBe("ok");
    expect(quotaLevel(80, 100)).toBe("warn");
    expect(quotaLevel(99, 100)).toBe("warn");
    expect(quotaLevel(100, 100)).toBe("full");
    expect(quotaLevel(5, 0)).toBe("ok");
    expect(quotaLevel(5, undefined)).toBe("ok");
  });
});

describe("quotaChips", () => {
  it("reports runs and LLM budget", () => {
    const chips = quotaChips(
      { runs: 9, cost_eur: 1 },
      { max_runs_per_month: 10, llm_budget_eur_per_month: 20 },
    );
    expect(chips.map((c) => [c.key, c.level])).toEqual([
      ["runs", "warn"],
      ["cost_eur", "ok"],
    ]);
  });
  it("skips metrics without a limit", () => {
    expect(quotaChips({ runs: 1 }, {})).toEqual([]);
  });
});
