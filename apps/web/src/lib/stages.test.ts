import { describe, expect, it } from "vitest";
import { formatDuration } from "./format";
import { collapseTrace, currentStage, executorKey, stageOf, stageStates } from "./stages";

describe("run stages", () => {
  it("maps graph nodes of both variants to stages", () => {
    expect(stageOf("extract_group")).toBe("normalize");
    expect(stageOf("normalize_group")).toBe("normalize");
    expect(stageOf("select_mpn")).toBe("select");
    expect(stageOf("validate")).toBe("validate");
    expect(stageOf("repair")).toBe("validate");
    expect(stageOf("compose")).toBe("assemble");
    expect(stageOf("assemble")).toBe("assemble");
  });

  it("leaves markers and unknown nodes out", () => {
    expect(stageOf("run.resumed")).toBeUndefined();
    expect(stageOf("claude_agent_sdk")).toBeUndefined();
    const s = stageStates("running", [{ node: "claude_agent_sdk", duration_s: 90, llm_calls: 3 }]);
    expect(s.every((x) => x.seconds === undefined)).toBe(true);
  });

  it("counts parallel fan-out of one node by its slowest call, not the sum", () => {
    const fan = Array.from({ length: 20 }, () => ({
      node: "select_mpn",
      duration_s: 3,
      llm_calls: 1,
    }));
    expect(collapseTrace(fan)).toEqual([{ node: "select_mpn", duration_s: 3, llm_calls: 20 }]);
    const s = stageStates("completed", [
      ...fan,
      { node: "validate", duration_s: 2, llm_calls: 0 },
      { node: "repair", duration_s: 4, llm_calls: 1 },
      { node: "validate", duration_s: 2, llm_calls: 0 },
    ]);
    expect(s[2]?.seconds).toBe(3);
    expect(s[2]?.llmCalls).toBe(20);
    expect(s[3]?.seconds).toBe(8);
  });

  it("marks done, current and future stages of a running run", () => {
    const s = stageStates("running", [
      { node: "normalize_group", duration_s: 4, llm_calls: 0 },
      { node: "select_mpn", duration_s: 41, llm_calls: 9 },
    ]);
    expect(s.map((x) => x.state)).toEqual(["done", "done", "done", "current", "todo"]);
    expect(currentStage(s)).toBe("validate");
    expect(s[2]?.seconds).toBe(41);
  });

  it("uses the last live step when the trace lags behind", () => {
    const s = stageStates("running", [], "select_mpn");
    expect(currentStage(s)).toBe("validate");
  });

  it("has no current stage when the run is finished or queued", () => {
    expect(stageStates("completed", []).every((x) => x.state === "done")).toBe(true);
    expect(currentStage(stageStates("queued", []))).toBeUndefined();
  });

  it("names the executor per variant", () => {
    const [read, norm, sel, val, asm] = stageStates("completed", [
      { node: "repair", duration_s: 1, llm_calls: 1 },
    ]);
    expect(executorKey("A", sel as never)).toBe("agent");
    expect(executorKey("B", read as never)).toBe("parser");
    expect(executorKey("B", norm as never)).toBe("rules");
    expect(executorKey("B", sel as never)).toBe("rulesAgent");
    expect(executorKey("B", val as never)).toBe("rulesRepair");
    expect(executorKey("B", asm as never)).toBe("generator");
  });

  it("formats durations like the sheet", () => {
    expect(formatDuration(18)).toBe("18 s");
    expect(formatDuration(62)).toBe("1 min 02 s");
    expect(formatDuration(3900)).toBe("1 h 05 min");
  });
});
