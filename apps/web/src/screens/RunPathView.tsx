import { type PathStep, ProvenanceRail, RunPath, VARIANT_KIND, VARIANT_TEXT } from "@bomagent/ui";
import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { type ReactNode, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api, call, type Schemas } from "../lib/api";
import { type LiveState, type Stage, stagesFromTrace } from "../lib/runPath";
import { useSession } from "../lib/session";
import { TERMINAL, useElapsed, useRunLive } from "../lib/useRunLive";

/**
 * The run path (docs/design/UX_GUIDELINES.md §3) with localised stage names and a textual
 * description for assistive technology. A running run shows one more, dashed stage.
 */
/** "select_mpn:C1" -> "MPN selection C1": the node name before the colon is localised. */
export function stageLabel(node: string, t: TFunction): string {
  const [base = node, ...rest] = node.split(":");
  const name = t(`run.nodes.${base}`, { defaultValue: base });
  return rest.length ? `${name} ${rest.join(":")}` : name;
}

export function RunPathView({
  stages,
  variant,
  running,
  drawIndex,
}: {
  stages: Stage[];
  variant: "A" | "B";
  running?: boolean;
  drawIndex?: number;
}) {
  const { t, i18n } = useTranslation();
  const seconds = useMemo(
    () => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }),
    [i18n.language],
  );
  const all: Stage[] = running
    ? [...stages, { node: "", actor: "parser", state: "running" as const }]
    : stages;
  const steps: PathStep[] = all.map((s, i) => ({
    id: `${s.node || "next"}-${i}`,
    label: s.node ? stageLabel(s.node, t) : t("run.path.pending"),
    actor: s.actor,
    detail: s.node
      ? [t(`run.actor.${s.actor}`), s.durationS != null ? `${seconds.format(s.durationS)} s` : ""]
          .filter(Boolean)
          .join(", ")
      : undefined,
    state: s.state,
  }));
  const description = t("run.path.describe", {
    variant,
    count: steps.length,
    stages: steps
      .map((s, i) =>
        t("run.path.stage", {
          n: i + 1,
          label: s.label,
          actor: t(`run.actor.${s.actor}`),
          state: t(`run.path.state.${s.state ?? "done"}`),
        }),
      )
      .join("; "),
  });
  return (
    <RunPath
      steps={steps}
      variant={variant}
      description={description}
      drawIndex={drawIndex}
      complete={!running && stages.length > 0}
    />
  );
}

/** Frame of one variant: provenance rail (hatched = A, solid = B), name, elapsed time. */
export function VariantFrame({
  variant,
  time,
  children,
  className,
}: {
  variant: "A" | "B";
  time?: string;
  children: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t("compare.framed", { variant, label: t(`compare.variant${variant}`) })}
      className={`relative border border-ink py-4 pl-9 pr-5 ${className ?? ""}`}
    >
      <ProvenanceRail kind={VARIANT_KIND[variant]} />
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className={`text-base font-semibold ${VARIANT_TEXT[variant]}`}>
          {t("compare.framed", { variant, label: t(`compare.variant${variant}`) })}
        </h3>
        {time ? <p className="font-mono text-sm">{time}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** The path of one run: live from SSE while it runs, from its trace when it has finished. */
export function RunPathPanel({
  run,
  live,
}: {
  run: Schemas["Run"];
  /** the caller already follows this run; otherwise the panel follows it itself */
  live?: LiveState;
}) {
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const own = useRunLive(run, live === undefined);
  const state = live ?? own.state;
  const finished = TERMINAL.has(run.status);
  const trace = useQuery({
    queryKey: ["trace", orgId, run.id],
    queryFn: () =>
      call(api.GET("/v1/runs/{run_id}/trace", { params: { path: { run_id: run.id } } })),
    enabled: finished && run.status !== "failed",
  });
  const variant = run.variant === "A" ? "A" : "B";
  const stages = finished
    ? stagesFromTrace(Array.isArray(trace.data) ? trace.data : [])
    : state.stages;
  const elapsed = useElapsed(run.started_at, !finished && run.status === "running");
  const seconds = Number(run.usage?.wall_time_s ?? 0) || (finished ? 0 : elapsed);
  return (
    <VariantFrame variant={variant} time={formatDuration(seconds, i18n.language)}>
      {stages.length || !finished ? (
        <RunPathView
          stages={stages}
          variant={variant}
          running={!finished}
          drawIndex={finished ? undefined : state.drawIndex}
        />
      ) : (
        <p className="text-sm text-ink-soft">{t("run.path.pending")}</p>
      )}
    </VariantFrame>
  );
}

/** "2 min 41 s", "12 s" */
export function formatDuration(totalSeconds: number, locale: string): string {
  const s = Math.round(totalSeconds);
  const n = new Intl.NumberFormat(locale);
  return s >= 60 ? `${n.format(Math.floor(s / 60))} min ${n.format(s % 60)} s` : `${n.format(s)} s`;
}
