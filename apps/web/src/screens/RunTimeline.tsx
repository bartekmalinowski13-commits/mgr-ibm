import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api, call } from "../lib/api";
import { useSession } from "../lib/session";

/** Steps of a finished run in order; violet = the step called an LLM, green = deterministic. */
export function RunTimeline({ runId }: { runId: string }) {
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const trace = useQuery({
    queryKey: ["trace", orgId, runId],
    queryFn: () =>
      call(api.GET("/v1/runs/{run_id}/trace", { params: { path: { run_id: runId } } })),
  });
  const steps = trace.data ?? [];
  if (!steps.length) return null;
  const seconds = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  return (
    <section aria-labelledby="timeline-title" className="flex flex-col gap-3">
      <h2 id="timeline-title" className="font-medium">
        {t("run.timeline")}
      </h2>
      <ol className="flex flex-wrap items-start gap-x-1 gap-y-3">
        {steps.map((s, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: steps are an ordered sequence; node names repeat
          <li key={`${s.node}-${i}`} className="flex items-start gap-1">
            <div className="flex min-w-[112px] flex-col gap-1 rounded-card border border-line bg-surface px-3 py-2">
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`size-2.5 shrink-0 rounded-full ${s.llm_calls > 0 ? "bg-llm" : "bg-rule"}`}
                />
                <span className="font-mono text-[13px]">{s.node}</span>
              </span>
              <span className="text-sm text-muted">
                {seconds.format(s.duration_s)} s
                {s.llm_calls > 0
                  ? ` – ${t("run.stepCalls", { count: s.llm_calls })}`
                  : ` – ${t("run.stepRule")}`}
              </span>
            </div>
            {i < steps.length - 1 ? <span aria-hidden className="mt-5 h-px w-3 bg-line" /> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
