import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Schemas } from "./api";
import { type RunProgress, streamRun } from "./api";
import { advanceLive, EMPTY_LIVE, type LiveState } from "./runPath";
import { useSession } from "./session";

export const TERMINAL = new Set(["completed", "failed", "budget_exceeded"]);

/** Follows a run over SSE until it ends; progress folds into the stages of the run path. */
export function useRunLive(run: Schemas["Run"] | undefined, enabled = true) {
  const queryClient = useQueryClient();
  const { orgId } = useSession();
  const [progress, setProgress] = useState<RunProgress>();
  const [state, setState] = useState<LiveState>(EMPTY_LIVE);
  useEffect(() => {
    if (!enabled || !run || TERMINAL.has(run.status)) return;
    const ctrl = new AbortController();
    void streamRun(
      run.id,
      (p) => {
        setProgress(p);
        setState((s) => advanceLive(s, p));
      },
      ctrl.signal,
    )
      .then(() => queryClient.invalidateQueries({ queryKey: ["run", orgId, run.id] }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [enabled, run, orgId, queryClient]);
  return { progress, state };
}

/** Seconds since `startedAt`, ticking once a second while `running`. */
export function useElapsed(startedAt: string | null | undefined, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);
  if (!startedAt) return 0;
  return Math.max(0, (now - new Date(startedAt).getTime()) / 1000);
}
