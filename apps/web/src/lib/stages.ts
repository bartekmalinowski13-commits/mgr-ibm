import type { ViaStep } from "@bomagent/ui";
import { formatDuration } from "./format";

/** The five stages a run is drawn with (ADR-0019 run sheet), whatever the graph's node names. */
export const STAGES = ["read", "normalize", "select", "validate", "assemble"] as const;
export type Stage = (typeof STAGES)[number];

export interface TraceStep {
  node: string;
  duration_s: number;
  llm_calls: number;
}

/** Graph node -> stage (variant A: extract_group/compose, B: normalize_group/repair/assemble). */
export function stageOf(node: string): Stage {
  const n = node.toLowerCase();
  if (n.includes("select") || n.includes("mpn")) return "select";
  if (n.includes("valid") || n.includes("repair")) return "validate";
  if (
    n.includes("compose") ||
    n.includes("assemble") ||
    n.includes("submit") ||
    n.includes("finish")
  )
    return "assemble";
  if (n.includes("parse") || n.includes("read")) return "read";
  return "normalize";
}

export interface StageState {
  stage: Stage;
  state: ViaStep["state"];
  seconds?: number;
  llmCalls: number;
  repaired: boolean;
}

/**
 * Where a run is: stages seen in the trace (or the last live step) and every stage before them
 * are done; the next one is current while the run is running. Reading the design happens at
 * upload time, so it is always done.
 */
export function stageStates(
  status: string,
  trace: TraceStep[],
  liveStep?: string | null,
): StageState[] {
  const index = (s: Stage) => STAGES.indexOf(s);
  let reached = 0; // index of the last finished stage
  for (const t of trace) reached = Math.max(reached, index(stageOf(t.node)));
  if (liveStep) reached = Math.max(reached, index(stageOf(liveStep)));
  const completed = status === "completed";
  const running = status === "running";
  return STAGES.map((stage, i) => {
    const steps = trace.filter((t) => stageOf(t.node) === stage);
    const done = completed || i <= reached;
    const current = running && !done && i === reached + 1;
    return {
      stage,
      state: done ? "done" : current ? "current" : "todo",
      seconds: steps.length ? steps.reduce((a, t) => a + t.duration_s, 0) : undefined,
      llmCalls: steps.reduce((a, t) => a + t.llm_calls, 0),
      repaired: steps.some((t) => t.node.toLowerCase().includes("repair")),
    };
  });
}

/** The stage a running run works on now (undefined when it is not running). */
export function currentStage(states: StageState[]): Stage | undefined {
  return states.find((s) => s.state === "current")?.stage;
}

/** Executor label key of a stage: who does the work in this variant. */
export function executorKey(variant: string, s: StageState): string {
  if (s.stage === "read") return "parser";
  if (variant === "A") return "agent";
  if (s.stage === "assemble") return "generator";
  if (s.stage === "validate") return s.repaired ? "rulesRepair" : "rules";
  if (s.stage === "select") return "rulesAgent";
  return s.llmCalls > 0 ? "rulesAgent" : "rules";
}

export function stageTime(s: StageState, runningLabel: string): string | undefined {
  if (s.state === "current") return runningLabel;
  if (s.seconds === undefined) return undefined;
  return formatDuration(s.seconds);
}
