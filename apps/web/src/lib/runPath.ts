import type { PathActor } from "@bomagent/ui";
import type { RunProgress } from "./api";

/** A stage of a run as the UI knows it: the graph node and who executed it. */
export interface Stage {
  node: string;
  actor: PathActor;
  durationS?: number;
  state: "done" | "running" | "pending";
}

export interface LiveState {
  stages: Stage[];
  /** LLM calls seen so far: a stage that raised the counter was an LLM stage */
  calls: number;
  /** index of the stage that finished with the latest event (its segment is drawn in) */
  drawIndex?: number;
}

export const EMPTY_LIVE: LiveState = { stages: [], calls: 0 };

/**
 * Folds a progress event of the SSE stream into the live stages. The stream reports the count
 * of finished steps and the last node; a stage is an LLM stage when the call counter rose
 * since the previous event. Events that arrive out of order or repeat change nothing.
 */
export function advanceLive(prev: LiveState, p: RunProgress): LiveState {
  const calls = Number(p.usage?.llm_calls ?? 0);
  if (p.steps <= prev.stages.length || !p.step) {
    return calls > prev.calls ? { ...prev, calls } : prev;
  }
  const stages = [...prev.stages];
  const missing = p.steps - stages.length;
  // when several steps finished between two events only the last name is known
  for (let i = 0; i < missing; i++) {
    const last = i === missing - 1;
    stages.push({
      node: last ? p.step : "…",
      actor: last && calls > prev.calls ? "llm" : "rule",
      state: "done",
    });
  }
  return { stages, calls, drawIndex: stages.length - 1 };
}

/** Stages of a finished run from `GET /v1/runs/{id}/trace`. */
export function stagesFromTrace(
  trace: { node: string; duration_s: number; llm_calls: number }[],
): Stage[] {
  return trace.map((s) => ({
    node: s.node,
    actor: s.llm_calls > 0 ? "llm" : "rule",
    durationS: s.duration_s,
    state: "done",
  }));
}
