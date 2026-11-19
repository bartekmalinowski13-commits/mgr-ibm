import { describe, expect, it } from "vitest";
import { runRoute } from "./router";

describe("run route (M-1)", () => {
  it("remounts the run screen when the run id changes (no stale live state after Rerun)", () => {
    const deps = runRoute.options.remountDeps as
      | ((opts: { params: { runId: string } }) => unknown)
      | undefined;
    expect(deps).toBeTypeOf("function");
    const a = deps?.({ params: { runId: "a" } });
    const b = deps?.({ params: { runId: "b" } });
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });
});
