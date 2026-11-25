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

/**
 * Graph node -> stage (variant A: extract_group/compose, B: normalize_group/repair/assemble).
 * Nodes that are not a pipeline step (e.g. `run.resumed`, the trace-cap marker, the single
 * `claude_agent_sdk` node of the SDK runtime) map to no stage and are left out of the tracks.
 */
export function stageOf(node: string): Stage | undefined {
  const n = node.toLowerCase();
  if (n.includes("select") || n.includes("mpn")) return "select";
  if (n.includes("valid") || n.includes("repair")) return "validate";
  if (n.includes("compose") || n.includes("assemble")) return "assemble";
  if (n.includes("extract") || n.includes("normali") || n.includes("group")) return "normalize";
  if (n.includes("parse")) return "read";
  return undefined;
}

/**
 * Consecutive trace rows of one node are parallel fan-out (one `select_mpn` per line, sent at
 * once), so they count as one step lasting as long as the slowest; repeats later in the trace
 * (another repair round) are new steps.
 */
export function collapseTrace(trace: TraceStep[]): TraceStep[] {
  const out: TraceStep[] = [];
  for (const t of trace) {
    const last = out[out.length - 1];
    if (last && last.node === t.node)
      out[out.length - 1] = {
        node: t.node,
        duration_s: Math.max(last.duration_s, t.duration_s),
        llm_calls: last.llm_calls + t.llm_calls,
      };
    else out.push({ ...t });
  }
  return out;
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
  const steps = collapseTrace(trace);
  let reached = 0; // index of the last finished stage
  for (const t of steps) {
    const s = stageOf(t.node);
    if (s) reached = Math.max(reached, index(s));
  }
  const live = liveStep ? stageOf(liveStep) : undefined;
  if (live) reached = Math.max(reached, index(live));
  const completed = status === "completed";
  const running = status === "running";
  return STAGES.map((stage, i) => {
    const own = steps.filter((t) => stageOf(t.node) === stage);
    const done = completed || i <= reached;
    const current = running && !done && i === reached + 1;
    return {
      stage,
      state: done ? "done" : current ? "current" : "todo",
      seconds: own.length ? own.reduce((a, t) => a + t.duration_s, 0) : undefined,
      llmCalls: own.reduce((a, t) => a + t.llm_calls, 0),
      repaired: own.some((t) => t.node.toLowerCase().includes("repair")),
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
