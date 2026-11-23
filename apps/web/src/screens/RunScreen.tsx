import { Button, ProvenanceSwatch, Sheet, VARIANT_TEXT } from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Ban, Download, RotateCw } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, downloadCsv, downloadXlsx, problemMessage, saveBlob } from "../lib/api";
import { formatNumber } from "../lib/format";
import { useIntentKeys } from "../lib/idempotency";
import { useDeskLayout, usePageTitle } from "../lib/layout";
import { type BomItem, formatEur, lineProvenance, type ProvenanceKind } from "../lib/provenance";
import { useRuns } from "../lib/queries";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { TERMINAL, useElapsed, useRunLive } from "../lib/useRunLive";
import { runRoute } from "../router";
import { BomTable } from "./BomTable";
import { LoadError, RunStatus, Skeleton } from "./common";
import { ItemPanel } from "./ItemPanel";
import { ReferencePanel } from "./ReferencePanel";
import { formatDuration, RunPathPanel, stageLabel } from "./RunPathView";
import { RunTitleBlock } from "./RunTitleBlock";
import { VersionHistory } from "./VersionHistory";

/** Runs of the two variants started together ("Both") are at most this far apart. */
const BOTH_WINDOW_MS = 120_000;
/** The API marks a cancelled run as failed with this error text. */
const CANCELLED = "cancelled by user";

export function RunScreen() {
  const { runId } = runRoute.useParams();
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const run = useQuery({
    queryKey: ["run", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })),
  });
  const { progress: live, state: liveState } = useRunLive(run.data);
  const siblings = useRuns(run.data?.project_id);
  const status = live?.status ?? run.data?.status;
  const finished = !!status && TERMINAL.has(status);
  const bom = useQuery({
    queryKey: ["bom", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}/bom", { params: { path: { run_id: runId } } })),
    enabled: status === "completed" || status === "budget_exceeded",
  });
  const [selected, setSelected] = useState<number>();
  const [rerunning, setRerunning] = useState(false);
  const elapsed = useElapsed(run.data?.started_at, status === "running");
  useDeskLayout();
  const keys = useIntentKeys();
  usePageTitle(
    run.data
      ? `${t("run.title")}: ${t("run.variant", { variant: run.data.variant })}`
      : t("run.title"),
  );

  const usage = (finished ? run.data?.usage : live?.usage) ?? run.data?.usage ?? {};
  const lang = i18n.language;
  const items = bom.data?.bom.items ?? [];
  const mix = useMemo(() => {
    const counts: Record<ProvenanceKind, number> = { rule: 0, agent: 0, parser: 0, user: 0 };
    for (const item of items) counts[lineProvenance(item)] += 1;
    return counts;
  }, [items]);
  const item: BomItem | undefined = items.find((i) => i.line === selected);

  if (run.isPending) return <Skeleton rows={4} />;
  if (run.isError) return <LoadError error={run.error} onRetry={() => void run.refetch()} />;

  const exportBom = async (format: "csv" | "xlsx") => {
    try {
      const blob = await (format === "csv" ? downloadCsv(runId) : downloadXlsx(runId));
      saveBlob(blob, `bom-${runId.slice(0, 8)}.${format}`);
      toast(t(format === "csv" ? "run.exported" : "run.exportedXlsx"));
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  const cancel = async () => {
    if (!window.confirm(t("run.confirmCancel"))) return;
    try {
      await call(api.POST("/v1/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }));
      await queryClient.invalidateQueries({ queryKey: ["run", orgId, runId] });
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("run.cancelled"));
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

  const rerun = async () => {
    if (rerunning) return;
    setRerunning(true);
    try {
      const next = await call(
        api.POST("/v1/runs/{run_id}/rerun", {
          params: { path: { run_id: runId } },
          // a retry after an error replays the same rerun instead of starting another one
          headers: { "Idempotency-Key": keys.keyFor(`rerun:${runId}`, runId) },
        }),
      );
      keys.done(`rerun:${runId}`);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast(t("run.rerunStarted"));
      await navigate({ to: "/runs/$runId", params: { runId: next.id } });
    } catch (err) {
      toast(problemMessage(err), "error");
    } finally {
      setRerunning(false);
    }
  };
  const cancelled = status === "failed" && run.data.error === CANCELLED;

  const counters = [
    { label: t("run.steps"), value: formatNumber(live?.steps ?? 0, lang), show: !finished },
    {
      label: t("run.llmCalls"),
      value: formatNumber(Number(usage.llm_calls ?? 0), lang),
      show: true,
    },
    {
      label: t("run.tokens"),
      value: formatNumber(Number(usage.input_tokens ?? 0) + Number(usage.output_tokens ?? 0), lang),
      show: true,
    },
    { label: t("run.cost"), value: formatEur(Number(usage.cost_eur ?? 0), lang), show: true },
    {
      label: t("run.time"),
      value: formatDuration(finished ? Number(usage.wall_time_s ?? 0) : elapsed, lang),
      show: finished || status === "running",
    },
  ].filter((c) => c.show);

  const sibling = siblings.data?.items.find(
    (r) =>
      r.id !== runId &&
      r.variant !== run.data.variant &&
      Math.abs(new Date(r.created_at).getTime() - new Date(run.data.created_at).getTime()) <
        BOTH_WINDOW_MS,
  );
  const variant = run.data.variant === "A" ? "A" : "B";

  return (
    <Sheet className="flex flex-col">
      <section
        aria-label={t("run.counters")}
        className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-ink px-5 py-3"
      >
        <RunStatus status={status ?? "queued"} />
        <span className="font-mono text-sm">{run.data.model_id}</span>
        <span className="font-mono text-sm text-ink-soft">{run.data.runtime}</span>
        {run.data.kb_snapshot_id ? (
          <span
            className="font-mono text-sm text-ink-soft"
            title={`${t("run.kbSnapshot")}: ${run.data.kb_snapshot_id}`}
          >
            {t("run.kbSnapshot")} {run.data.kb_snapshot_id.slice(0, 12)}
          </span>
        ) : null}
        <div className="ml-auto flex flex-wrap gap-2">
          {status === "queued" || status === "running" ? (
            <Button variant="danger" size="sm" onClick={() => void cancel()}>
              <Ban size={16} aria-hidden /> {t("run.cancel")}
            </Button>
          ) : null}
          {finished ? (
            <Button variant="secondary" size="sm" disabled={rerunning} onClick={() => void rerun()}>
              <RotateCw size={16} aria-hidden /> {t("run.rerun")}
            </Button>
          ) : null}
          {status === "completed" ? (
            <>
              <Button variant="secondary" size="sm" onClick={() => void exportBom("csv")}>
                <Download size={16} aria-hidden /> {t("run.export")}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => void exportBom("xlsx")}>
                <Download size={16} aria-hidden /> {t("run.exportXlsx")}
              </Button>
            </>
          ) : null}
        </div>
      </section>
      <dl className="grid grid-cols-2 border-b border-ink sm:grid-cols-4">
        {counters.map((c) => (
          <div key={c.label} className="border-r border-rule px-5 py-3 last:border-r-0">
            <dt className="text-sm text-ink-soft">{c.label}</dt>
            <dd className="font-mono text-2xl font-medium tabular-nums">{c.value}</dd>
          </div>
        ))}
      </dl>

      {status === "queued" ? <p className="px-5 pt-4 text-ink-soft">{t("run.waiting")}</p> : null}
      {status !== "failed" ? (
        <section aria-labelledby="path-title" className="flex flex-col gap-3 px-5 py-5">
          <h2 id="path-title" className="font-display text-2xl font-semibold tracking-[-0.01em]">
            {sibling ? t("run.pathBoth") : t("run.path.label")}
          </h2>
          {status === "running" ? (
            <p aria-live="polite" className="text-sm text-ink-soft">
              {live?.step
                ? t("run.lastStep", {
                    step: stageLabel(live.step, t),
                  })
                : t("run.starting")}
            </p>
          ) : null}
          <div className={sibling ? "grid gap-4 lg:grid-cols-2" : undefined}>
            {sibling && variant === "B" ? <RunPathPanel run={sibling} /> : null}
            <RunPathPanel
              run={{ ...run.data, status: status ?? run.data.status }}
              live={liveState}
            />
            {sibling && variant === "A" ? <RunPathPanel run={sibling} /> : null}
          </div>
        </section>
      ) : null}
      {cancelled ? (
        <p role="status" className="px-5 pb-4 text-ink-soft">
          {t("run.cancelledHelp")}
        </p>
      ) : status === "failed" ? (
        <p role="alert" className="px-5 pb-4 text-status-error">
          {t("run.failedHelp", { error: run.data.error ?? "" })}
        </p>
      ) : null}

      {bom.isPending && finished && status !== "failed" ? (
        <div className="px-5 pb-5">
          <Skeleton rows={6} />
        </div>
      ) : null}
      {bom.isError ? (
        <div className="px-5 pb-5">
          <LoadError error={bom.error} />
        </div>
      ) : null}
      {bom.data ? (
        <section aria-labelledby="bom-title" className="flex flex-col border-t border-ink">
          <div className="flex flex-col xl:flex-row xl:items-stretch">
            <div className="flex min-w-0 flex-1 flex-col gap-4 p-5">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-baseline gap-x-4">
                    <h2
                      id="bom-title"
                      className="font-display text-[40px] font-semibold leading-none tracking-[-0.01em]"
                    >
                      {t("bom.title")}
                    </h2>
                    <p className={`font-semibold ${VARIANT_TEXT[variant]}`}>
                      {t("run.variant", { variant })}, {t(`compare.variant${variant}`)}
                    </p>
                  </div>
                  <p className="mt-2 text-sm text-ink-soft">
                    {bom.data.bom.design_name} – {t("run.version", { version: bom.data.version })} –{" "}
                    {t("run.findings", { count: bom.data.bom.findings?.length ?? 0 })}
                  </p>
                </div>
                <ProvenanceMix counts={mix} />
              </div>
              <BomTable bom={bom.data.bom} selected={selected} onSelect={setSelected} />
              <RunTitleBlock run={run.data} version={bom.data.version} />
              <div className="mt-2">
                <VersionHistory runId={runId} current={bom.data.version} />
              </div>
              <div className="mt-2">
                <ReferencePanel runId={runId} />
              </div>
            </div>
            {item ? (
              <ItemPanel
                runId={runId}
                item={item}
                findings={bom.data.bom.findings ?? []}
                onClose={() => setSelected(undefined)}
              />
            ) : null}
          </div>
        </section>
      ) : null}
    </Sheet>
  );
}

/** Who decided the lines: share per provenance, in the same pattern and colour as the row rails. */
function ProvenanceMix({ counts }: { counts: Record<ProvenanceKind, number> }) {
  const { t } = useTranslation();
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const kinds = (Object.keys(counts) as ProvenanceKind[]).filter((k) => counts[k] > 0);
  return (
    <figure className="w-full max-w-[420px]">
      <figcaption className="mb-1.5 text-sm text-ink-soft">{t("bom.origin")}</figcaption>
      <div className="flex h-3 border border-ink" aria-hidden>
        {kinds.map((k) => (
          <span
            key={k}
            className={`rail-${k}`}
            style={{ width: `${(counts[k] / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {kinds.map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <ProvenanceSwatch kind={k} />
            {t(`bom.provenance.${k}`)}: <span className="font-mono">{counts[k]}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
