import type { Run } from "../api/types";
import { pickPair } from "./Compare";

const run = (id: string, variant: string, design: string, status = "completed"): Run => ({
  id,
  variant,
  design_id: design,
  status,
  model_id: "fake-closed",
  created_by: "u",
  created_at: "2026-11-10T00:00:00Z",
});

describe("pickPair", () => {
  const runs = [
    run("b2", "B", "d2"),
    run("a1", "A", "d1"),
    run("b1", "B", "d1"),
    run("a3", "A", "d3", "running"),
  ];

  it("pairs the latest finished A and B on the same design", () => {
    expect(pickPair(runs)?.map((r) => r.id)).toEqual(["a1", "b1"]);
  });

  it("honours runs named in the URL and finds the partner for one", () => {
    expect(pickPair(runs, "a1", "b2")?.map((r) => r.id)).toEqual(["a1", "b2"]);
    expect(pickPair(runs, undefined, "b1")?.map((r) => r.id)).toEqual(["a1", "b1"]);
  });

  it("returns null without a finished pair", () => {
    expect(pickPair([run("a3", "A", "d3", "running"), run("b3", "B", "d3")])).toBeNull();
  });
});
