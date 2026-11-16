import { describe, expect, it } from "vitest";
import { firstBomSteps } from "./checklist";

describe("firstBomSteps", () => {
  it("marks steps done in order and reports the first open one", () => {
    expect(firstBomSteps({ projects: 0, runs: 0, completed: 0 })).toEqual({
      steps: [
        { key: "project", done: false },
        { key: "run", done: false },
        { key: "review", done: false },
      ],
      next: "project",
      complete: false,
    });
    const s = firstBomSteps({ projects: 2, runs: 1, completed: 0 });
    expect(s.next).toBe("review");
    expect(s.steps.map((x) => x.done)).toEqual([true, true, false]);
    expect(firstBomSteps({ projects: 1, runs: 1, completed: 1 }).complete).toBe(true);
  });
});
