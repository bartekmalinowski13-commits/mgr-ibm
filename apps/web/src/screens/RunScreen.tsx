import { Button } from "@bomagent/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, call, downloadCsv, problemMessage, type RunProgress, streamRun } from "../lib/api";
import { formatNumber } from "../lib/format";
import { usePageTitle } from "../lib/layout";
import {
  type BomItem,
  formatEur,
  lineProvenance,
  PROVENANCE_COLOR,
  type ProvenanceKind,
} from "../lib/provenance";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { runRoute } from "../router";
import { BomTable } from "./BomTable";
import { LoadError, RunStatus, Skeleton } from "./common";
import { ItemPanel } from "./ItemPanel";
import { ReferencePanel } from "./ReferencePanel";
import { RunTimeline } from "./RunTimeline";

const TERMINAL = new Set(["completed", "failed", "budget_exceeded"]);

export function RunScreen() {
  const { runId } = runRoute.useParams();
  const { t, i18n } = useTranslation();
  const { orgId } = useSession();
  const toast = useToast();
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["run", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })),
  });
  const [live, setLive] = useState<RunProgress>();
  const status = live?.status ?? run.data?.status;
  const finished = !!status && TERMINAL.has(status);
  const bom = useQuery({
    queryKey: ["bom", orgId, runId],
    queryFn: () => call(api.GET("/v1/runs/{run_id}/bom", { params: { path: { run_id: runId } } })),
    enabled: status === "completed" || status === "budget_exceeded",
  });
  const [selected, setSelected] = useState<number>();
  usePageTitle(
    run.data
      ? `${t("run.title")}: ${t("run.variant", { variant: run.data.variant })}`
      : t("run.title"),
  );

  useEffect(() => {
    if (!run.data || TERMINAL.has(run.data.status)) return;
    const ctrl = new AbortController();
    void streamRun(runId, setLive, ctrl.signal)
      .then(() => queryClient.invalidateQueries({ queryKey: ["run", orgId, runId] }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [run.data, runId, orgId, queryClient]);

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

  const exportCsv = async () => {
    try {
      const blob = await downloadCsv(runId);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `bom-${runId.slice(0, 8)}.csv`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      toast(t("run.exported"));
    } catch (err) {
      toast(problemMessage(err), "error");
    }
  };

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
      value: `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(Number(usage.wall_time_s ?? 0))} s`,
      show: finished,
    },
  ].filter((c) => c.show);

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4 rounded-panel border border-line bg-surface p-5">
        <div className="flex flex-wrap items-center gap-3">
          <RunStatus status={status ?? "queued"} />
          <span className="font-mono text-sm text-muted">{run.data.model_id}</span>
          <span className="font-mono text-sm text-muted">{run.data.runtime}</span>
          {status === "completed" ? (
            <Button
              variant="secondary"
              size="sm"
              className="ml-auto"
              onClick={() => void exportCsv()}
            >
              <Download size={16} aria-hidden /> {t("run.export")}
            </Button>
          ) : null}
        </div>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {counters.map((c) => (
            <div key={c.label}>
              <dt className="text-sm text-muted">{c.label}</dt>
              <dd className="font-display text-2xl font-bold tabular-nums">{c.value}</dd>
            </div>
          ))}
        </dl>
        {status === "queued" ? <p className="text-muted">{t("run.waiting")}</p> : null}
        {finished && status !== "failed" ? <RunTimeline runId={runId} /> : null}
        {status === "failed" ? (
          <p role="alert" className="text-error">
            {t("run.failedHelp", { error: run.data.error ?? "" })}
          </p>
        ) : null}
        {status === "running" ? (
          <div className="flex flex-col gap-2">
            <div aria-hidden className="flex flex-wrap gap-1.5">
              {Array.from({ length: Math.max(1, live?.steps ?? 0) }, (_, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: one dot per finished step
                <span key={i} className="size-2.5 rounded-full bg-llm motion-safe:animate-pulse" />
              ))}
            </div>
            <p aria-live="polite" className="text-sm text-muted">
              {live?.step ? t("run.lastStep", { step: live.step }) : t("run.starting")}
            </p>
          </div>
        ) : null}
      </section>

      {bom.isPending && finished && status !== "failed" ? <Skeleton rows={6} /> : null}
      {bom.isError ? <LoadError error={bom.error} /> : null}
      {bom.data ? (
        <section aria-labelledby="bom-title" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 id="bom-title" className="font-display text-2xl font-bold">
                {t("bom.title")}
              </h2>
              <p className="text-sm text-muted">
                {bom.data.bom.design_name} – {t("run.version", { version: bom.data.version })} –{" "}
                {t("run.findings", { count: bom.data.bom.findings?.length ?? 0 })}
              </p>
            </div>
            <ProvenanceMix counts={mix} />
          </div>
          <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-start">
            <div className="min-w-0 flex-1">
              <BomTable bom={bom.data.bom} selected={selected} onSelect={setSelected} />
              <div className="mt-6">
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
    </div>
  );
}

/** Who decided the lines: share per provenance, in the same colours as the row stripes. */
function ProvenanceMix({ counts }: { counts: Record<ProvenanceKind, number> }) {
  const { t } = useTranslation();
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const kinds = (Object.keys(counts) as ProvenanceKind[]).filter((k) => counts[k] > 0);
  return (
    <figure className="w-full max-w-[420px]">
      <figcaption className="mb-1.5 text-sm text-muted">{t("bom.origin")}</figcaption>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-line" aria-hidden>
        {kinds.map((k) => (
          <span
            key={k}
            className={PROVENANCE_COLOR[k]}
            style={{ width: `${(counts[k] / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {kinds.map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span aria-hidden className={`size-2.5 rounded-full ${PROVENANCE_COLOR[k]}`} />
            {t(`bom.provenance.${k}`)}: {counts[k]}
          </li>
        ))}
      </ul>
    </figure>
  );
}
